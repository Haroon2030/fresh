import logging
import re

import requests
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


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
    return bool(
        getattr(settings, "EVOLUTION_SERVER_URL", "")
        and getattr(settings, "EVOLUTION_API_KEY", "")
    )


def notify_enabled() -> bool:
    return bool(
        getattr(settings, "EVOLUTION_NOTIFY_ENABLED", False)
        and getattr(settings, "EVOLUTION_SERVER_URL", "")
        and getattr(settings, "EVOLUTION_API_KEY", "")
    )


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "apikey": settings.EVOLUTION_API_KEY,
    }


def _api(path: str, method: str = "GET", json_body=None, timeout: int = 20):
    url = f"{settings.EVOLUTION_SERVER_URL.rstrip('/')}{path}"
    verify = getattr(settings, "EVOLUTION_VERIFY_SSL", True)
    try:
        if not verify:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.request(
            method,
            url,
            headers=_headers(),
            json=json_body,
            timeout=timeout,
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
    configured = (getattr(settings, "EVOLUTION_INSTANCE_NAME", "") or "").strip()
    return configured or "farshops"


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
    if not getattr(settings, "EVOLUTION_SERVER_URL", "") or not getattr(
        settings, "EVOLUTION_API_KEY", ""
    ):
        return {
            "ok": False,
            "configured": False,
            "state": "unconfigured",
            "instance": "",
            "detail": "أضف EVOLUTION_SERVER_URL و EVOLUTION_API_KEY.",
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
                break
        # Never trust a lone 'open' from fetchInstances if connectionState says close
        state_l = str(state).lower()
        if state_l not in ("open", "close", "connecting"):
            state = fetch_status or state
        elif state_l == "open" and fetch_status == "close":
            state = "close"
        elif state_l == "close":
            state = "close"
        # open without ownerJid is often a zombie socket
        elif state_l == "open" and not owner and fetch_status != "open":
            state = "close"

    ok = str(state).lower() == "open" and bool(owner or fetch_status == "open")
    # Extra safety: open + empty owner from both → still show as connecting
    if str(state).lower() == "open" and not owner:
        ok = False
        state = "connecting"

    return {
        "ok": ok,
        "configured": True,
        "state": state,
        "instance": instance,
        "owner": owner,
        "status_code": status,
        "detail": data,
    }


def fetch_qr() -> dict:
    if not getattr(settings, "EVOLUTION_SERVER_URL", "") or not settings.EVOLUTION_API_KEY:
        return {"ok": False, "error": "إعدادات Evolution غير مكتملة."}

    instance = resolve_instance_name()
    state_info = connection_state()
    if state_info.get("ok"):
        return {
            "ok": True,
            "connected": True,
            "base64": "",
            "pairingCode": "",
            "state": "open",
            "instance": instance,
            "message": "الواتساب متصل بالفعل — لا حاجة لـ QR.",
        }

    # Ensure instance exists
    names = {
        (i.get("name") or i.get("instanceName") or "")
        for i in list_instances()
    }
    if instance not in names:
        created = create_instance()
        if not created.get("ok"):
            return {"ok": False, "error": created.get("error") or "تعذّر إنشاء انستانس."}
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

    # Refresh websocket + QR
    _api(f"/instance/restart/{instance}", method="POST")
    status, data = _api(f"/instance/connect/{instance}")
    base64, pairing, code = _extract_qr(data if isinstance(data, dict) else {})

    if status == 404:
        created = create_instance()
        if created.get("ok"):
            return fetch_qr()
        return {
            "ok": False,
            "error": created.get("error") or "الانستانس غير موجود وتعذّر إنشاؤه.",
            "detail": data,
        }

    if status == 0 or status >= 400:
        err = data.get("error") or data.get("message") or "فشل جلب رمز QR"
        if isinstance(err, list):
            err = " | ".join(str(x) for x in err)
        return {
            "ok": False,
            "error": str(err),
            "detail": data,
            "status_code": status,
            "server_url": settings.EVOLUTION_SERVER_URL,
            "instance": instance,
        }

    if not base64 and not pairing:
        return {
            "ok": False,
            "error": (
                "لم يُرجع Evolution صورة QR. من الجوال: واتساب ← الأجهزة المرتبطة ← "
                "احذف أي جهاز Evolution قديم، ثم اضغط «إعادة إنشاء الانستانس»."
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
    if not settings.EVOLUTION_API_KEY or not settings.EVOLUTION_SERVER_URL:
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
    )
    if status >= 400 or status == 0:
        msg = str(data)
        logger.warning("Evolution send failed (%s): %s", status, msg[:500])
        if "connection closed" in msg.lower():
            # surface for callers that check return False + logs
            logger.error(
                "Evolution instance socket dead (Connection Closed). "
                "Set EVOLUTION_INSTANCE_NAME=farshops and re-scan QR."
            )
        return False
    return True


def send_document(
    number: str,
    pdf_bytes: bytes,
    *,
    filename: str,
    caption: str = "",
) -> bool:
    """Send a PDF via Evolution /message/sendMedia (mediatype=document)."""
    import base64

    if not notify_enabled():
        return False
    phone = normalize_whatsapp(number)
    if not phone or not pdf_bytes:
        return False
    instance = resolve_instance_name()
    if not instance:
        return False

    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    media = f"data:application/pdf;base64,{b64}"
    status, data = _api(
        f"/message/sendMedia/{instance}",
        method="POST",
        json_body={
            "number": phone,
            "mediatype": "document",
            "mimetype": "application/pdf",
            "media": media,
            "fileName": filename or "document.pdf",
            "caption": (caption or "")[:1024],
        },
        timeout=60,
    )
    if status >= 400 or status == 0:
        logger.warning("Evolution sendMedia failed (%s): %s", status, str(data)[:500])
        return False
    return True


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
) -> dict:
    """
    Send structured text then PDF to each recipient.
    recipients: list of {phone, label, role}
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
    if not pdf_bytes:
        return {"sent": 0, "total": len(recipients), "phones": [], "error": "تعذّر إنشاء ملف PDF."}

    sent = 0
    phones = []
    for entry in recipients:
        phone = entry.get("phone") or ""
        phones.append(phone)
        dest = entry.get("label") or entry.get("role") or ""
        text = message
        if dest:
            text = f"{message}\nإلى: {dest}"
        short_caption = f"المرفق الرسمي: {filename}"
        # Send PDF first so recipient can download the file, then the details text
        ok_pdf = send_document(phone, pdf_bytes, filename=filename, caption=short_caption)
        ok_text = send_text(phone, text)
        if ok_text or ok_pdf:
            sent += 1

    err = None
    if sent == 0:
        # Distinguish empty phones vs dead session
        if not any(phones):
            err = "لا توجد أرقام واتساب للمستلمين. احفظ أرقام الأدوار في شاشة واتساب."
        else:
            err = (
                "فشل إرسال واتساب: الجلسة غير مربوطة (Connection Closed). "
                "افتح /whatsapp/ → تحديث QR وامسح الرمز."
            )
    return {"sent": sent, "total": len(recipients), "phones": phones, "error": err}


def send_test_to_roles() -> dict:
    return notify_roles("اختبار إشعار", "هذه رسالة تجريبية من عمليات الفرش.")
