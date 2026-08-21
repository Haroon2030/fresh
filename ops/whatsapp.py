import logging
import re

import requests
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


def _strip_env_val(raw) -> str:
    if raw is None:
        return ""
    val = str(raw).replace("\ufeff", "").strip()
    if len(val) >= 2 and val[0] in ('"', "'", "“", "”", "‘", "’") and val[-1] in ('"', "'", "“", "”", "‘", "’"):
        val = val[1:-1].strip()
    if val.replace("•", "").strip() == "":
        return ""
    return val


def get_evolution_settings() -> dict:
    """
    Resolve Evolution config: environment first, then DB (Dokploy often drops API key).
    """
    db = None
    try:
        from ops.models import EvolutionConfig
        db = EvolutionConfig.objects.order_by("pk").first()
    except Exception:
        db = None

    server_url = (
        _strip_env_val(getattr(settings, "EVOLUTION_SERVER_URL", ""))
        or _strip_env_val(getattr(db, "server_url", "") if db else "")
        or "http://72.61.107.230:8081"
    ).rstrip("/")
    api_key = (
        _strip_env_val(getattr(settings, "EVOLUTION_API_KEY", ""))
        or _strip_env_val(getattr(db, "api_key", "") if db else "")
    )
    instance_name = (
        _strip_env_val(getattr(settings, "EVOLUTION_INSTANCE_NAME", ""))
        or _strip_env_val(getattr(db, "instance_name", "") if db else "")
        or "farshops"
    )
    if db is not None and (db.api_key or db.server_url):
        notify = bool(db.notify_enabled)
        verify_ssl = bool(db.verify_ssl)
    else:
        notify = bool(getattr(settings, "EVOLUTION_NOTIFY_ENABLED", False))
        verify_ssl = bool(getattr(settings, "EVOLUTION_VERIFY_SSL", False))

    return {
        "server_url": server_url,
        "api_key": api_key,
        "instance_name": instance_name,
        "notify_enabled": bool(notify and api_key and server_url),
        "verify_ssl": verify_ssl,
        "source": "env" if _strip_env_val(getattr(settings, "EVOLUTION_API_KEY", "")) else (
            "db" if (db and db.api_key) else "none"
        ),
    }


def normalize_whatsapp(number: str) -> str:
    """Normalize to international digits (default Saudi 966)."""
    raw = (number or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    # 05xxxxxxxx → 9665xxxxxxxx
    if len(digits) == 10 and digits.startswith("05"):
        digits = "966" + digits[1:]
    # 5xxxxxxxx (9 digits) → 9665xxxxxxxx
    if len(digits) == 9 and digits.startswith("5"):
        digits = "966" + digits
    return digits


def is_configured() -> bool:
    cfg = get_evolution_settings()
    return bool(cfg["server_url"] and cfg["api_key"])


def notify_enabled() -> bool:
    return bool(get_evolution_settings()["notify_enabled"])


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "apikey": get_evolution_settings()["api_key"],
    }


def _api(path: str, method: str = "GET", json_body=None, timeout: int | tuple = 20):
    cfg = get_evolution_settings()
    url = f"{cfg['server_url'].rstrip('/')}{path}"
    verify = cfg["verify_ssl"]
    try:
        if not verify:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # (connect timeout, read timeout) — sendMedia/PDF can be slow
        if isinstance(timeout, (int, float)):
            req_timeout = (min(15, float(timeout)), float(timeout))
        else:
            req_timeout = timeout
        response = requests.request(
            method,
            url,
            headers=_headers(),
            json=json_body,
            timeout=req_timeout,
            verify=verify,
        )
        raw = response.text or ""
        content_type = (response.headers.get("Content-Type") or "").lower()
        data = {}
        if "application/json" in content_type or raw.lstrip().startswith(("{", "[")):
            try:
                data = response.json()
            except ValueError:
                data = {"raw": raw[:500]}
        else:
            snippet = " ".join(raw.split())[:180]
            data = {
                "error": (
                    f"الرابط لا يفتح Evolution API (HTTP {response.status_code}). "
                    "استخدم http://IP:8081 إن كان يعمل مع نظامك الآخر."
                ),
                "raw": snippet,
            }
        return response.status_code, data
    except requests.RequestException as exc:
        logger.exception("Evolution API error: %s %s", method, path)
        return 0, {"error": f"تعذّر الاتصال بـ Evolution: {exc}"}


def list_instances() -> list:
    status, data = _api("/instance/fetchInstances")
    if status != 200:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("instance", "instances", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def resolve_instance_name() -> str:
    """Always use configured name only — never auto-pick a zombie 'open' instance."""
    return get_evolution_settings()["instance_name"] or "farshops"


def _normalize_qr_base64(base64: str) -> str:
    if base64 and not str(base64).startswith("data:"):
        return f"data:image/png;base64,{base64}"
    return base64 or ""


def _extract_qr(data: dict) -> tuple[str, str, str]:
    if not isinstance(data, dict):
        return "", "", ""
    base64 = (
        data.get("base64")
        or (data.get("qrcode") or {}).get("base64")
        or ""
    )
    pairing = data.get("pairingCode") or (data.get("qrcode") or {}).get("pairingCode") or ""
    code = data.get("code") or (data.get("qrcode") or {}).get("code") or ""
    return _normalize_qr_base64(base64), pairing or "", code or ""


def connection_state() -> dict:
    if not is_configured():
        return {
            "ok": False,
            "configured": False,
            "state": "unconfigured",
            "instance": "",
            "detail": "احفظ مفتاح API من شاشة واتساب أو أضفه في Dokploy.",
        }

    instance = resolve_instance_name()
    status, data = _api(f"/instance/connectionState/{instance}")
    state = (
        (data.get("instance") or {}).get("state")
        or data.get("state")
        or ("error" if status >= 400 or status == 0 else "unknown")
    )
    owner = ""
    fetch_status = ""
    disc_reason = ""
    # Instance missing → treat as closed so UI shows QR / recreate
    if status == 404:
        state = "close"
    else:
        for inst in list_instances():
            name = inst.get("name") or inst.get("instanceName")
            if name == instance:
                fetch_status = str(
                    inst.get("connectionStatus") or inst.get("status") or ""
                ).lower()
                owner = inst.get("ownerJid") or inst.get("owner") or ""
                disc_reason = str(inst.get("disconnectionReasonCode") or "")
                break
        state_l = str(state).lower()
        # 401/440 = logged out / replaced — status may still say open with stale owner
        if disc_reason in ("401", "403", "440", "515"):
            state = "connecting"
        elif fetch_status == "open" and owner:
            # Trust owned open session — connectionState often flickers to connecting
            state = "open"
        elif state_l == "open" and fetch_status == "close":
            state = "close"
        elif state_l == "close":
            state = "close"
        elif state_l not in ("open", "close", "connecting"):
            state = fetch_status or state
        elif state_l == "open" and not owner and fetch_status != "open":
            state = "close"

    ok = str(state).lower() == "open" and bool(owner) and disc_reason not in (
        "401",
        "403",
        "440",
        "515",
    )
    if str(state).lower() == "open" and not owner:
        # open without owner is unreliable — show closed, not endless connecting
        ok = False
        state = "close"
    if disc_reason in ("401", "403", "440", "515"):
        ok = False
        state = "connecting"

    return {
        "ok": ok,
        "configured": True,
        "state": state,
        "instance": instance,
        "owner": owner,
        "disc_reason": disc_reason,
        "status_code": status,
        "detail": data,
    }


def _evolution_error_text(data) -> str:
    """Human-readable Evolution error (Arabic-friendly)."""
    if not isinstance(data, dict):
        return str(data or "خطأ غير معروف")
    msg = data.get("message")
    if isinstance(msg, list):
        msg = " | ".join(str(x) for x in msg)
    if not msg:
        nested = data.get("response") if isinstance(data.get("response"), dict) else {}
        msg = nested.get("message") if isinstance(nested, dict) else None
        if isinstance(msg, list):
            msg = " | ".join(str(x) for x in msg)
    err = data.get("error") or ""
    parts = [p for p in (str(msg or "").strip(), str(err).strip()) if p]
    text = " — ".join(dict.fromkeys(parts)) if parts else "خطأ غير معروف"
    # Soften opaque API labels
    if text.lower() in ("bad request", "forbidden", "not found"):
        text = (
            f"{text}. الانستانس غير جاهز — جرّب «إعادة إنشاء» مرة واحدة، "
            "أو تأكد أن Evolution يعمل ثم حدّث الصفحة."
        )
    return text


def fetch_qr(*, force: bool = False) -> dict:
    if not is_configured():
        return {"ok": False, "error": "إعدادات Evolution غير مكتملة."}

    instance = resolve_instance_name()
    state_info = connection_state()
    if state_info.get("ok") and not force:
        return {
            "ok": True,
            "connected": True,
            "base64": "",
            "pairingCode": "",
            "state": "open",
            "instance": instance,
            "message": "الواتساب متصل بالفعل — لا حاجة لـ QR.",
        }

    names = {
        (i.get("name") or i.get("instanceName") or "")
        for i in list_instances()
    }
    exists = instance in names

    # Missing instance → create (do not restart — restart on missing = Bad Request)
    if not exists:
        created = create_instance()
        if not created.get("ok"):
            return {
                "ok": False,
                "error": created.get("error") or "تعذّر إنشاء انستانس farshops.",
                "instance": instance,
            }
        base64, pairing, code = _extract_qr(created.get("detail") or {})
        if base64 or pairing:
            return {
                "ok": True,
                "connected": False,
                "base64": base64,
                "pairingCode": pairing,
                "code": code,
                "state": "connecting",
                "instance": instance,
            }
        # Create ok but no QR in body — fall through to connect
        exists = True

    # force refresh: restart only when instance exists
    if force and exists:
        _api(f"/instance/restart/{instance}", method="POST")

    status, data = _api(f"/instance/connect/{instance}")
    base64, pairing, code = _extract_qr(data if isinstance(data, dict) else {})

    if status == 404:
        created = create_instance()
        if created.get("ok"):
            base64, pairing, code = _extract_qr(created.get("detail") or {})
            if base64 or pairing:
                return {
                    "ok": True,
                    "connected": False,
                    "base64": base64,
                    "pairingCode": pairing,
                    "code": code,
                    "state": "connecting",
                    "instance": instance,
                }
            status, data = _api(f"/instance/connect/{instance}")
            base64, pairing, code = _extract_qr(data if isinstance(data, dict) else {})
        else:
            return {
                "ok": False,
                "error": created.get("error") or "الانستانس غير موجود وتعذّر إنشاؤه.",
                "detail": data,
            }

    if status == 0 or status >= 400:
        return {
            "ok": False,
            "error": _evolution_error_text(data if isinstance(data, dict) else {"error": data}),
            "detail": data,
            "status_code": status,
            "server_url": get_evolution_settings()["server_url"],
            "instance": instance,
        }

    if not base64 and not pairing:
        again = connection_state()
        if again.get("ok"):
            return {
                "ok": True,
                "connected": True,
                "base64": "",
                "pairingCode": "",
                "state": "open",
                "instance": instance,
                "message": "الواتساب متصل بالفعل — لا حاجة لـ QR.",
            }
        return {
            "ok": False,
            "error": (
                "لم يُرجع Evolution صورة QR. من الجوال: واتساب ← الأجهزة المرتبطة ← "
                "احذف أي جهاز Evolution قديم، ثم اضغط «إعادة إنشاء» مرة واحدة فقط وامسح."
            ),
            "detail": data,
            "state": state_info.get("state"),
            "instance": instance,
        }

    return {
        "ok": True,
        "connected": False,
        "base64": base64,
        "pairingCode": pairing,
        "code": code,
        "state": "connecting",
        "instance": instance,
        "detail": data,
    }


def create_instance() -> dict:
    if not is_configured():
        return {"ok": False, "error": "إعدادات Evolution غير مكتملة."}
    instance = resolve_instance_name()
    status, data = _api(
        "/instance/create",
        method="POST",
        json_body={
            "instanceName": instance,
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS",
            "alwaysOnline": True,
            "readMessages": False,
            "readStatus": False,
            "syncFullHistory": False,
            "groupsIgnore": True,
        },
    )
    if status in (200, 201):
        # Stabilize session settings (always online helps keep socket alive)
        _api(
            f"/settings/set/{instance}",
            method="POST",
            json_body={
                "rejectCall": False,
                "groupsIgnore": True,
                "alwaysOnline": True,
                "readMessages": False,
                "readStatus": False,
                "syncFullHistory": False,
            },
        )
        return {"ok": True, "detail": data}
    msg = str(data)
    if "already" in msg.lower() or status == 403:
        return {"ok": True, "detail": data, "exists": True}
    err = data.get("error") or data.get("message") or f"HTTP {status}"
    if isinstance(err, list):
        err = " | ".join(str(x) for x in err)
    return {"ok": False, "error": err, "detail": data}


def delete_instance(instance: str | None = None) -> dict:
    instance = (instance or resolve_instance_name()).strip()
    if not instance:
        return {"ok": False, "error": "لا يوجد انستانس."}
    status, data = _api(f"/instance/delete/{instance}", method="DELETE")
    return {"ok": status in (200, 201), "detail": data, "status_code": status}


def logout_instance() -> dict:
    instance = resolve_instance_name()
    if not instance:
        return {"ok": False, "error": "لا يوجد انستانس."}
    status, data = _api(f"/instance/logout/{instance}", method="DELETE")
    # Dead sockets often fail logout — still treat as "need QR"
    if status not in (200, 201):
        _api(f"/instance/restart/{instance}", method="POST")
    return {
        "ok": True,
        "detail": data,
        "status_code": status,
        "instance": instance,
        "message": "تم طلب قطع الاتصال. حدّث QR وامسح الرمز.",
    }


def recreate_instance() -> dict:
    """Delete + create configured instance and return a fresh QR."""
    instance = resolve_instance_name()
    _api(f"/instance/logout/{instance}", method="DELETE")
    deleted = delete_instance(instance)
    created = create_instance()
    if created.get("exists") and not deleted.get("ok"):
        # stuck name: try connect on existing, else spin a fresh name suffix
        qr = fetch_qr()
        if qr.get("ok") and (qr.get("base64") or qr.get("pairingCode")):
            qr["deleted"] = deleted
            qr["recreate_warning"] = (
                "تعذّر حذف الانستانس القديم. جُلب QR للجلسة الحالية — امسحه فوراً."
            )
            return qr
        # last resort: farshops / farshops2 style
        alt = "farshops" if instance != "farshops" else "farshops2"
        status, data = _api(
            "/instance/create",
            method="POST",
            json_body={
                "instanceName": alt,
                "qrcode": True,
                "integration": "WHATSAPP-BAILEYS",
            },
        )
        if status in (200, 201):
            base64, pairing, code = _extract_qr(data if isinstance(data, dict) else {})
            return {
                "ok": True,
                "connected": False,
                "base64": base64,
                "pairingCode": pairing,
                "code": code,
                "state": "connecting",
                "instance": alt,
                "recreated": True,
                "recreate_warning": (
                    f"تم إنشاء انستانس بديل «{alt}». ضع EVOLUTION_INSTANCE_NAME={alt} في Dokploy ثم Redeploy."
                ),
            }
        qr = fetch_qr()
        qr["deleted"] = deleted
        return qr
    if not created.get("ok"):
        return {
            "ok": False,
            "error": created.get("error") or "تعذّر إعادة إنشاء الانستانس.",
            "deleted": deleted,
            "instance": instance,
        }
    base64, pairing, code = _extract_qr(created.get("detail") or {})
    if not base64 and not pairing:
        return fetch_qr()
    return {
        "ok": True,
        "connected": False,
        "base64": base64,
        "pairingCode": pairing,
        "code": code,
        "state": "connecting",
        "instance": instance,
        "recreated": True,
        "deleted": deleted,
    }


def send_text(number: str, text: str) -> bool:
    if not notify_enabled():
        logger.warning("WhatsApp notify disabled or incomplete settings")
        return False
    phone = normalize_whatsapp(number)
    if not phone or not text:
        return False

    instance = resolve_instance_name()
    if not instance:
        logger.warning("No Evolution instance for send")
        return False

    status, data = _api(
        f"/message/sendText/{instance}",
        method="POST",
        json_body={"number": phone, "text": text},
        timeout=15,
    )
    if status >= 400 or status == 0:
        msg = str(data)
        logger.warning("Evolution send failed (%s): %s", status, msg[:500])
        if "connection closed" in msg.lower() or "timed out" in msg.lower():
            logger.error(
                "Evolution instance unreachable or dead. "
                "Check EVOLUTION_INSTANCE_NAME=farshops and re-scan QR."
            )
        return False
    return True


def send_document(
    number: str,
    pdf_bytes: bytes,
    *,
    filename: str,
    caption: str = "",
    media_url: str = "",
) -> bool:
    """
    Send a PDF via Evolution /message/sendMedia.

    Prefer public URL (fast for Evolution), then raw base64.
    Avoid long multipart hangs — they kill Gunicorn workers (worker timeout).
    """
    import base64
    import re as _re

    if not notify_enabled():
        return False
    phone = normalize_whatsapp(number)
    if not phone:
        return False
    instance = resolve_instance_name()
    if not instance:
        return False

    raw_name = (filename or "document.pdf").replace('"', "").replace("#", "")
    raw_name = _re.sub(r"[^\w.\-]+", "_", raw_name, flags=_re.UNICODE).strip("._") or "document"
    if not raw_name.lower().endswith(".pdf"):
        raw_name = f"{raw_name}.pdf"
    filename = raw_name
    caption = (caption or "")[:1024]

    url_media = ""
    if media_url and str(media_url).startswith(("http://", "https://")):
        url_media = str(media_url)
        if not url_media.lower().endswith(".pdf"):
            url_media = url_media.rstrip("/") + "/document.pdf"

    # Keep each attempt short so the request/thread cannot stall past Gunicorn timeout
    send_timeout = 18

    # 1) Public URL ending with .pdf (Evolution downloads; our HTTP returns quickly)
    if url_media:
        status, data = _api(
            f"/message/sendMedia/{instance}",
            method="POST",
            json_body={
                "number": phone,
                "mediatype": "document",
                "mimetype": "application/pdf",
                "media": url_media,
                "fileName": filename,
                "caption": caption,
            },
            timeout=send_timeout,
        )
        if status and status < 400:
            return True
        logger.warning("Evolution sendMedia url failed (%s): %s", status, str(data)[:400])
        if "connection closed" in str(data).lower():
            return False

    # 2) Raw base64 (no data: URI — rejected by this Evolution build)
    if pdf_bytes:
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        status, data = _api(
            f"/message/sendMedia/{instance}",
            method="POST",
            json_body={
                "number": phone,
                "mediatype": "document",
                "mimetype": "application/pdf",
                "media": b64,
                "fileName": filename,
                "caption": caption,
            },
            timeout=send_timeout,
        )
        if status and status < 400:
            return True
        logger.warning("Evolution sendMedia base64 failed (%s): %s", status, str(data)[:400])

    return False


def _user_phone(user) -> str:
    if not user:
        return ""
    return normalize_whatsapp(getattr(user, "whatsapp", "") or "")


def _role_contact_phone(role: str) -> str:
    from ops.models import WhatsAppRoleContact

    contact = WhatsAppRoleContact.objects.filter(role=role).exclude(phone="").first()
    return normalize_whatsapp(contact.phone) if contact else ""


def collect_recipient_entries(*, include_roles: bool = True) -> list[dict]:
    """
    Recipients for operational alerts.
    Each: {phone, label, role, user_id?}
    """
    from ops.models import WhatsAppRoleContact

    entries = []
    seen = set()

    def add(phone: str, label: str, role: str, user_id=None):
        phone = normalize_whatsapp(phone)
        if not phone or phone in seen:
            return
        seen.add(phone)
        entries.append(
            {"phone": phone, "label": label, "role": role, "user_id": user_id}
        )

    if include_roles:
        role_labels = dict(WhatsAppRoleContact.ROLE_CHOICES)
        for contact in WhatsAppRoleContact.objects.filter(role__in=User.NOTIFY_ROLES).exclude(
            phone=""
        ):
            add(
                contact.phone,
                f"{role_labels.get(contact.role, contact.role)} (جدول الأدوار)",
                contact.role,
            )
        for user in User.objects.filter(is_active=True, role__in=User.NOTIFY_ROLES).exclude(
            whatsapp=""
        ):
            add(
                user.whatsapp,
                f"{user.display_name} — {user.get_role_display()}",
                user.role,
                user.pk,
            )
    return entries


def notify_user(user, title: str, body: str = "") -> bool:
    if not user or not notify_enabled():
        return False
    phone = _user_phone(user)
    if not phone:
        logger.info("Skip WhatsApp: user %s has no whatsapp number", getattr(user, "pk", "?"))
        return False
    message = f"[عمليات الفرش] {title}"
    if body:
        message = f"{message}\n{body}"
    return send_text(phone, message)


def collect_notify_phones() -> list[str]:
    """Unique phones for NOTIFY_ROLES (role contacts + users)."""
    return [e["phone"] for e in collect_recipient_entries(include_roles=True)]


def notify_roles(title: str, body: str = "") -> dict:
    """
    Send WhatsApp to role contact numbers + active users in NOTIFY_ROLES.
    Returns {sent, total, phones, error}.
    """
    if not notify_enabled():
        return {"sent": 0, "total": 0, "phones": [], "error": "الإشعارات غير مفعّلة أو الإعدادات ناقصة."}

    phones = collect_notify_phones()
    if not phones:
        return {
            "sent": 0,
            "total": 0,
            "phones": [],
            "error": "لا توجد أرقام واتساب. احفظ أرقام الأدوار في شاشة واتساب أولاً.",
        }

    message = f"[عمليات الفرش] {title}"
    if body:
        message = f"{message}\n{body}"

    sent = 0
    for phone in phones:
        if send_text(phone, message):
            sent += 1
    err = None
    if sent == 0:
        err = (
            "فشل الإرسال: جلسة واتساب غير جاهزة (Connection Closed). "
            "من شاشة واتساب: تحديث QR وامسح الرمز من جديد للانستانس farshops."
        )
    return {"sent": sent, "total": len(phones), "phones": phones, "error": err}


def notify_with_pdf(
    *,
    message: str,
    pdf_bytes: bytes,
    filename: str,
    recipients: list[dict],
    media_url: str = "",
) -> dict:
    """
    One WhatsApp message per recipient: PDF document + full text as caption.
    Falls back to text-only if media send fails.
    """
    if not notify_enabled():
        return {"sent": 0, "total": 0, "phones": [], "error": "الإشعارات غير مفعّلة أو الإعدادات ناقصة."}
    if not recipients:
        return {
            "sent": 0,
            "total": 0,
            "phones": [],
            "error": "لا توجد أرقام واتساب للمستلمين.",
        }
    if not pdf_bytes and not media_url:
        return {"sent": 0, "total": len(recipients), "phones": [], "error": "تعذّر إنشاء ملف PDF."}

    # Deduplicate by phone so the same number never gets multiple bubbles
    unique: list[dict] = []
    seen = set()
    for entry in recipients:
        phone = entry.get("phone") or ""
        if not phone or phone in seen:
            continue
        seen.add(phone)
        unique.append(entry)

    sent = 0
    phones = []
    for entry in unique:
        phone = entry.get("phone") or ""
        phones.append(phone)
        caption = (entry.get("message") or message or "").strip()
        # WhatsApp caption hard limit ~1024
        if len(caption) > 1000:
            caption = caption[:997] + "…"
        try:
            ok = send_document(
                phone,
                pdf_bytes or b"",
                filename=filename,
                caption=caption,
                media_url=media_url,
            )
            if not ok:
                # Last resort: text alone (still one message)
                ok = send_text(phone, caption or message)
            if ok:
                sent += 1
        except Exception:
            logger.exception("WhatsApp notify failed for %s", phone)

    err = None
    if sent == 0:
        if not any(phones):
            err = "لا توجد أرقام واتساب للمستلمين. احفظ أرقام الأدوار في شاشة واتساب."
        else:
            err = (
                "فشل إرسال واتساب: الجلسة غير مربوطة أو Evolution بطيء. "
                "افتح /whatsapp/ → تحديث QR وامسح الرمز (farshops)."
            )
    return {"sent": sent, "total": len(unique), "phones": phones, "error": err}


def send_test_to_roles() -> dict:
    return notify_roles("اختبار إشعار", "هذه رسالة تجريبية من عمليات الفرش.")
