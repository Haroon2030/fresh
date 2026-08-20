import logging
import re

import requests
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


def normalize_whatsapp(number: str) -> str:
    """Normalize to digits only; convert leading 00 to country format."""
    raw = (number or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def is_configured() -> bool:
    return bool(
        getattr(settings, "EVOLUTION_SERVER_URL", "")
        and getattr(settings, "EVOLUTION_API_KEY", "")
        and getattr(settings, "EVOLUTION_INSTANCE_NAME", "")
    )


def notify_enabled() -> bool:
    return bool(getattr(settings, "EVOLUTION_NOTIFY_ENABLED", False) and is_configured())


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
        data = {}
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text[:500]}
        return response.status_code, data
    except requests.RequestException as exc:
        logger.exception("Evolution API error: %s %s", method, path)
        return 0, {"error": str(exc)}


def connection_state() -> dict:
    """Return {ok, state, configured, instance, detail}."""
    if not is_configured():
        return {
            "ok": False,
            "configured": False,
            "state": "unconfigured",
            "instance": "",
            "detail": "أضف إعدادات Evolution في البيئة (SERVER / API_KEY / INSTANCE).",
        }
    instance = settings.EVOLUTION_INSTANCE_NAME
    status, data = _api(f"/instance/connectionState/{instance}")
    state = (
        (data.get("instance") or {}).get("state")
        or data.get("state")
        or ("error" if status >= 400 or status == 0 else "unknown")
    )
    return {
        "ok": status == 200 and str(state).lower() == "open",
        "configured": True,
        "state": state,
        "instance": instance,
        "status_code": status,
        "detail": data,
    }


def fetch_qr() -> dict:
    """
    Request QR / pairing for the configured instance.
    Returns {ok, base64, pairingCode, code, state, error}.
    """
    if not is_configured():
        return {"ok": False, "error": "إعدادات Evolution غير مكتملة."}

    instance = settings.EVOLUTION_INSTANCE_NAME
    status, data = _api(f"/instance/connect/{instance}")

    # Some deployments nest QR under qrcode.base64
    base64 = (
        data.get("base64")
        or (data.get("qrcode") or {}).get("base64")
        or ""
    )
    if base64 and not str(base64).startswith("data:"):
        base64 = f"data:image/png;base64,{base64}"

    pairing = data.get("pairingCode") or ""
    code = data.get("code") or ""

    if status == 404:
        # try create then connect again
        created = create_instance()
        if created.get("ok"):
            return fetch_qr()
        return {
            "ok": False,
            "error": created.get("error") or "الانستانس غير موجود وتعذّر إنشاؤه.",
            "detail": data,
        }

    if status == 0 or status >= 400:
        return {
            "ok": False,
            "error": (data.get("error") or data.get("message") or "فشل جلب رمز QR"),
            "detail": data,
            "status_code": status,
        }

    state_info = connection_state()
    if state_info.get("ok"):
        return {
            "ok": True,
            "connected": True,
            "base64": "",
            "pairingCode": "",
            "state": "open",
            "message": "الواتساب متصل بالفعل.",
        }

    return {
        "ok": True,
        "connected": False,
        "base64": base64,
        "pairingCode": pairing,
        "code": code,
        "state": state_info.get("state"),
        "detail": data,
    }


def create_instance() -> dict:
    if not is_configured():
        return {"ok": False, "error": "إعدادات Evolution غير مكتملة."}
    instance = settings.EVOLUTION_INSTANCE_NAME
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
    # already exists
    msg = str(data)
    if "already" in msg.lower() or status == 403:
        return {"ok": True, "detail": data, "exists": True}
    return {
        "ok": False,
        "error": data.get("error") or data.get("message") or f"HTTP {status}",
        "detail": data,
    }


def logout_instance() -> dict:
    if not is_configured():
        return {"ok": False, "error": "غير مُعدّ."}
    instance = settings.EVOLUTION_INSTANCE_NAME
    status, data = _api(f"/instance/logout/{instance}", method="DELETE")
    return {"ok": status in (200, 201), "detail": data, "status_code": status}


def send_text(number: str, text: str) -> bool:
    if not notify_enabled():
        return False
    phone = normalize_whatsapp(number)
    if not phone or not text:
        return False

    status, data = _api(
        f"/message/sendText/{settings.EVOLUTION_INSTANCE_NAME}",
        method="POST",
        json_body={"number": phone, "text": text},
    )
    if status >= 400 or status == 0:
        logger.warning("Evolution send failed (%s): %s", status, str(data)[:500])
        return False
    return True


def notify_user(user, title: str, body: str = "") -> bool:
    """Send WhatsApp to a single user if they have a number. Never raises."""
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


def _role_contact_phones(roles) -> set[str]:
    from ops.models import WhatsAppRoleContact

    phones = set()
    for contact in WhatsAppRoleContact.objects.filter(role__in=roles).exclude(phone=""):
        phone = normalize_whatsapp(contact.phone)
        if phone:
            phones.add(phone)
    return phones


def notify_roles(title: str, body: str = "") -> int:
    """
    Send WhatsApp to role contact numbers + active users in NOTIFY_ROLES.
    Returns count of successful sends. Never raises.
    """
    if not notify_enabled():
        return 0

    message = f"[عمليات الفرش] {title}"
    if body:
        message = f"{message}\n{body}"

    seen = _role_contact_phones(User.NOTIFY_ROLES)

    recipients = (
        User.objects.filter(
            is_active=True,
            role__in=User.NOTIFY_ROLES,
        )
        .exclude(whatsapp="")
        .only("id", "whatsapp", "username")
    )
    for user in recipients:
        phone = normalize_whatsapp(user.whatsapp)
        if phone:
            seen.add(phone)

    sent = 0
    for phone in seen:
        if send_text(phone, message):
            sent += 1
    return sent
