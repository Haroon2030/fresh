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
    return configured or "farsh"


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
    # Instance missing → treat as closed so UI shows QR / recreate
    if status == 404:
        state = "close"
    elif status != 200 or str(state).lower() not in ("open", "close", "connecting"):
        for inst in list_instances():
            name = inst.get("name") or inst.get("instanceName")
            if name == instance:
                state = inst.get("connectionStatus") or inst.get("status") or state
                break

    return {
        "ok": str(state).lower() == "open",
        "configured": True,
        "state": state,
        "instance": instance,
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
        },
    )
    if status in (200, 201):
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
        # stuck name: force QR via restart+connect
        qr = fetch_qr()
        qr["deleted"] = deleted
        qr["recreate_warning"] = (
            "تعذّر حذف الانستانس من السيرفر. جُلب QR للجلسة الحالية. "
            "من الجوال احذف الأجهزة المرتبطة القديمة ثم امسح الرمز فوراً."
        )
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
                "Set EVOLUTION_INSTANCE_NAME=farsh and re-scan QR."
            )
        return False
    return True


def notify_user(user, title: str, body: str = "") -> bool:
    if not user or not notify_enabled():
        return False
    phone = normalize_whatsapp(getattr(user, "whatsapp", "") or "")
    if not phone:
        logger.info("Skip WhatsApp: user %s has no whatsapp number", getattr(user, "pk", "?"))
        return False
    message = f"[عمليات الفرش] {title}"
    if body:
        message = f"{message}\n{body}"
    return send_text(phone, message)


def collect_notify_phones() -> list[str]:
    """Unique phones for NOTIFY_ROLES (role contacts + users)."""
    from ops.models import WhatsAppRoleContact

    seen = []
    found = set()

    for contact in WhatsAppRoleContact.objects.filter(role__in=User.NOTIFY_ROLES).exclude(phone=""):
        phone = normalize_whatsapp(contact.phone)
        if phone and phone not in found:
            found.add(phone)
            seen.append(phone)

    for user in (
        User.objects.filter(is_active=True, role__in=User.NOTIFY_ROLES)
        .exclude(whatsapp="")
        .only("whatsapp")
    ):
        phone = normalize_whatsapp(user.whatsapp)
        if phone and phone not in found:
            found.add(phone)
            seen.append(phone)
    return seen


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
            "فشل الإرسال: جلسة واتساب ميتة (Connection Closed). "
            "ضع EVOLUTION_INSTANCE_NAME=farsh ثم اقطع الاتصال/حدّث QR وامسح الرمز من جديد."
        )
    return {"sent": sent, "total": len(phones), "phones": phones, "error": err}


def send_test_to_roles() -> dict:
    return notify_roles("اختبار إشعار", "هذه رسالة تجريبية من عمليات الفرش.")
