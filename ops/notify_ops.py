"""Structured WhatsApp+PDF notifications for ops documents."""
from __future__ import annotations

import logging
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone

from ops.pdf_docs import (
    build_daily_orders_pdf,
    build_distribution_batch_pdf,
    build_return_batch_pdf,
    build_supply_orders_pdf,
    build_task_pdf,
    build_variance_batch_pdf,
    role_label,
)
from ops.whatsapp import (
    build_wa_notice,
    build_wa_pdf_caption,
    collect_recipient_entries,
    notify_with_pdf,
    normalize_whatsapp,
)
from ops.models import ReturnBatch, WhatsAppRoleContact


def _user_phone(user) -> str:
    if not user:
        return ""
    phone = normalize_whatsapp(getattr(user, "whatsapp", "") or "")
    if phone:
        return phone
    role = getattr(user, "role", "") or ""
    if role:
        return _role_contact_phone(role)
    return ""


def _role_contact_phone(role: str) -> str:
    contact = WhatsAppRoleContact.objects.filter(role=role).exclude(phone="").first()
    return normalize_whatsapp(contact.phone) if contact else ""

logger = logging.getLogger(__name__)


def _run_in_background(label: str, fn, *args, **kwargs) -> None:
    """Fire-and-forget so HTTP workers never wait on Evolution."""

    def _job():
        close_old_connections()
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception("Background WhatsApp job failed: %s", label)
        finally:
            close_old_connections()

    threading.Thread(target=_job, name=f"wa-{label}", daemon=True).start()


def schedule_return_notify(batch_id: int, actor_id: int) -> None:
    def _run():
        User = get_user_model()
        batch = (
            ReturnBatch.objects.select_related("representative", "created_by")
            .prefetch_related("items")
            .filter(pk=batch_id)
            .first()
        )
        actor = User.objects.filter(pk=actor_id).first()
        if not batch or not actor:
            return
        notify_return_batch_saved(batch, actor=actor, request=None)

    _run_in_background(f"return-{batch_id}", _run)


def schedule_supply_notify(order_ids: list[int], actor_id: int, representative_id: int) -> None:
    def _run():
        from ops.models import SupplyOrder

        User = get_user_model()
        orders = list(
            SupplyOrder.objects.select_related("representative", "created_by")
            .filter(pk__in=order_ids)
            .order_by("pk")
        )
        actor = User.objects.filter(pk=actor_id).first()
        representative = User.objects.filter(pk=representative_id).first()
        if not orders or not actor or not representative:
            return
        notify_supply_orders_saved(orders, actor=actor, representative=representative)

    _run_in_background(f"supply-{order_ids[:1]}", _run)


def _now_str() -> str:
    return timezone.localtime().strftime("%Y-%m-%d %H:%M")


def _portal_hint() -> str:
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    if base:
        return f"🌐 بوابة النظام: {base}"
    return "ادخل النظام لمتابعة العملية."


def _return_pdf_url(batch, request=None) -> str:
    batch.ensure_public_token()
    if not batch.public_token:
        batch.save(update_fields=["public_token"])
    # Path ends with .pdf so WhatsApp / Evolution treat it as a real document
    path = reverse(
        "ops:return_batch_pdf_public_file",
        kwargs={"token": batch.public_token},
    )
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    if base:
        return f"{base}{path}"
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def _actor_line(user) -> str:
    return f"{user.display_name} | {role_label(user)}"


def _pdf_caption(title: str, *, instruction: str = "") -> str:
    """رسالة واتساب لمرفق PDF — بدون تفاصيل (يكفي الملف)."""
    return build_wa_pdf_caption(title, instruction=instruction)


def _compact_wa(
    title: str,
    *,
    file_ref: str = "",
    meta: str = "",
    bullets: list[str] | None = None,
    note: str = "",
    pdf_url: str = "",
) -> str:
    """Legacy wrapper — PDF captions are short; details live in the attachment."""
    if pdf_url or not (file_ref or meta or bullets):
        return _pdf_caption(title, instruction=note)
    return build_wa_notice(title, body=note or meta)


def _public_pdf_url(route_name: str, token: str, request=None) -> str:
    path = reverse(route_name, kwargs={"token": token})
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    if base:
        return f"{base}{path}"
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def _sync_batch_token(model, *, batch_number: str = "", pks: list[int] | None = None) -> str:
    import secrets

    qs = model.objects.all()
    if pks:
        qs = qs.filter(pk__in=pks)
    elif batch_number:
        qs = qs.filter(batch_number=batch_number)
    else:
        return ""
    row = qs.exclude(public_token="").first()
    token = row.public_token if row else secrets.token_urlsafe(24)
    qs.update(public_token=token)
    return token


def _notify_pdf_to_roles(
    message: str,
    *,
    pdf_bytes: bytes,
    filename: str,
    pdf_url: str,
    roles: set | None = None,
    extra: list[dict] | None = None,
) -> dict:
    recipients = [
        {**entry, "message": entry.get("message") or message}
        for entry in collect_recipient_entries(include_roles=True, roles=roles)
    ]
    seen = {r["phone"] for r in recipients if r.get("phone")}
    for entry in extra or []:
        phone = entry.get("phone") or ""
        if phone and phone not in seen:
            recipients.append({**entry, "message": entry.get("message") or message})
            seen.add(phone)
    if not recipients:
        return {"sent": 0, "total": 0, "phones": [], "error": "لا مستلمين."}
    return notify_with_pdf(
        message=message,
        pdf_bytes=pdf_bytes,
        filename=filename,
        recipients=recipients,
        media_url=pdf_url,
    )


def _notify_pdf_to_user(
    user,
    message: str,
    *,
    pdf_bytes: bytes,
    filename: str,
    pdf_url: str,
) -> dict:
    phone = _user_phone(user)
    if not phone:
        return {"sent": 0, "total": 0, "phones": [], "error": "لا رقم واتساب."}
    return notify_with_pdf(
        message=message,
        pdf_bytes=pdf_bytes,
        filename=filename,
        recipients=[{
            "phone": phone,
            "label": user.display_name,
            "role": getattr(user, "role", ""),
            "user_id": user.pk,
            "message": message,
        }],
        media_url=pdf_url,
    )


def notify_return_batch_saved(batch, *, actor, request=None) -> dict:
    """
    On saving a return file (قبل التعميد):
    - PDF للمندوب للتعميد
    - PDF للعمليات والمحاسب للمتابعة
    """
    User = get_user_model()
    try:
        pdf_bytes, filename = build_return_batch_pdf(batch)
    except Exception:
        logger.exception("PDF build failed for return %s", getattr(batch, "pk", "?"))
        return {"sent": 0, "total": 0, "phones": [], "error": "تعذّر إنشاء PDF للمرتجع."}

    pdf_url = _return_pdf_url(batch, request=request)

    follow_msg = _pdf_caption(
        "إشعار مرتجع — للمتابعة",
        instruction="نُرفق ملف المرتجع. يرجى متابعة الإجراء حتى الاكتمال.",
    )
    rep_msg = _pdf_caption(
        "إشعار مرتجع — مطلوب تعميدكم",
        instruction="نُرفق ملف المرتجع. يرجى المراجعة والتعميد أو الرفض.",
    )

    follow_roles = {User.Role.MANAGER, User.Role.ACCOUNTANT}
    recipients = collect_recipient_entries(include_roles=True, roles=follow_roles)
    rep = batch.representative
    rep_phone = _user_phone(rep) or _role_contact_phone("representative")

    enriched = []
    seen = set()
    for entry in recipients:
        phone = entry.get("phone") or ""
        if not phone or phone in seen:
            continue
        seen.add(phone)
        enriched.append({**entry, "message": follow_msg})

    if rep_phone and rep_phone not in seen:
        enriched.append(
            {
                "phone": rep_phone,
                "label": f"{rep.display_name} — {role_label(rep)}",
                "role": "representative",
                "user_id": getattr(rep, "pk", None),
                "message": rep_msg,
            }
        )
        seen.add(rep_phone)
    elif rep_phone and rep_phone in seen:
        for entry in enriched:
            if entry.get("phone") == rep_phone:
                entry["message"] = rep_msg
                entry["role"] = "representative"
                break

    result = notify_with_pdf(
        message=follow_msg,
        pdf_bytes=pdf_bytes,
        filename=filename,
        recipients=enriched,
        media_url=pdf_url,
    )
    result["pdf_url"] = pdf_url
    result["pdf_filename"] = filename
    result["rep_notified"] = bool(rep_phone and rep_phone in (result.get("phones") or []) and result.get("sent"))
    if not rep_phone:
        result["rep_notified"] = False
        result["rep_warning"] = (
            "المندوب بلا رقم واتساب — أضف رقمه في ملف المستخدم أو جدول الأدوار في /whatsapp/."
        )
        if not result.get("error"):
            result["error"] = result["rep_warning"]
        elif "بلا رقم" not in (result.get("error") or ""):
            result["error"] = f"{result['error']} | {result['rep_warning']}"

    return result


def notify_supply_orders_saved(orders: list, *, actor, representative) -> dict:
    if not orders:
        return {"sent": 0, "total": 0, "phones": [], "error": "لا طلبات."}
    from ops.models import SupplyOrder

    try:
        pdf_bytes, filename = build_supply_orders_pdf(orders, actor=actor)
    except Exception:
        logger.exception("PDF build failed for supply")
        return {"sent": 0, "total": 0, "phones": [], "error": "تعذّر إنشاء PDF للتوريد."}

    first = orders[0]
    batch_ref = first.batch_number or first.order_number
    token = _sync_batch_token(
        SupplyOrder,
        batch_number=first.batch_number or "",
        pks=[o.pk for o in orders] if not first.batch_number else None,
    )
    if not token and first.batch_number:
        token = _sync_batch_token(SupplyOrder, batch_number=first.batch_number)
    if not token:
        token = _sync_batch_token(SupplyOrder, pks=[o.pk for o in orders])
    pdf_url = _public_pdf_url("ops:supply_batch_pdf_public_file", token)

    msg = _pdf_caption(
        "إشعار توريد",
        instruction="نُرفق ملف التوريد. يرجى المراجعة والتنسيق.",
    )

    rep_phone = _user_phone(representative) or _role_contact_phone("representative")
    extra = []
    if rep_phone:
        extra.append({
            "phone": rep_phone,
            "label": f"{representative.display_name} — {role_label(representative)}",
            "role": "representative",
            "user_id": getattr(representative, "pk", None),
            "message": msg,
        })

    return _notify_pdf_to_roles(
        msg,
        pdf_bytes=pdf_bytes,
        filename=filename,
        pdf_url=pdf_url,
        roles=get_user_model().NOTIFY_ROLES,
        extra=extra,
    )


def _absolute_public_url(path: str, request=None) -> str:
    """رابط عام كامل — واتساب يفعّل النقر فقط مع http(s)."""
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    if base:
        return f"{base}{path}"
    if request is not None:
        return request.build_absolute_uri(path)
    hosts = getattr(settings, "ALLOWED_HOSTS", []) or []
    for host in hosts:
        h = (host or "").strip()
        if h and h not in ("*", "localhost", "127.0.0.1", "[::1]"):
            scheme = "http" if h.startswith("127.") or h.startswith("192.168.") else "https"
            return f"{scheme}://{h}{path}"
    return path


def _task_public_url(task, request=None) -> str:
    path = reverse("ops:task_public", kwargs={"token": task.public_token})
    return _absolute_public_url(path, request=request)


def _format_due_at(task) -> str:
    if not task.due_at:
        return "—"
    return timezone.localtime(task.due_at).strftime("%Y/%m/%d %H:%M")


def _build_task_wa_message(
    task,
    *,
    kind: str = "assigned",
    review_note: str = "",
) -> str:
    """
    رسالة واتساب احترافية للمهام (بدون الرابط — يُرسل في رسالة مستقلة).
    kind: assigned | correction
    """
    assignee = task.assigned_to.display_name if task.assigned_to_id else "الموظف"

    if kind == "correction":
        title = "إشعار مهمة — مطلوب تصحيح"
        intro = f"السلام عليكم *{assignee}*،"
        instruction = (
            "تمت مراجعة ردكم ويُطلب التعديل قبل الإغلاق."
            + (
                f"\nملاحظة المراجعة: {(review_note or task.review_note or '').strip()}"
                if (review_note or task.review_note or "").strip()
                else ""
            )
            + "\nيرجى الرد عبر الرابط أدناه."
        )
    else:
        title = "إشعار مهمة تشغيلية"
        intro = f"السلام عليكم *{assignee}*،"
        instruction = (
            f"تم إسناد مهمة: *{task.title}*\n"
            f"الموعد: {_format_due_at(task)}\n"
            "يرجى الرد عبر الرابط أدناه."
        )

    body = build_wa_pdf_caption(title, instruction=instruction)
    return f"{intro}\n\n{body}"


def _send_whatsapp_link(phone: str, message: str, link: str, *, link_label: str = "فتح صفحة الرد") -> bool:
    """زر URL + رابط PUBLIC_BASE_URL (نطاق أو sslip.io للـ IP)."""
    from ops.whatsapp import send_clickable_link

    link = (link or "").strip()
    if not phone or not link:
        return False
    body = (message or "").strip()
    if link in body:
        body = body.replace(link, "").strip()
    return send_clickable_link(phone, body, link, button_text=link_label)


def send_task_link_now(task, *, public_link: str = "", kind: str = "assigned") -> dict:
    """إرسال رسالة المهمة + رابط الرد فوراً (للإنشاء أو إعادة الإرسال)."""
    task.ensure_public_token()
    if not task.public_token:
        task.save(update_fields=["public_token"])
    if not task.assigned_to_id:
        return {"ok": False, "error": "لا يوجد موظف معيّن للمهمة."}
    phone = _user_phone(task.assigned_to)
    if not phone:
        return {
            "ok": False,
            "error": "الموظف بلا رقم واتساب — أضف الرقم من شاشة المستخدمين.",
        }
    link = (public_link or "").strip() or _task_public_url(task)
    if not link.startswith("http"):
        return {
            "ok": False,
            "error": "رابط غير كامل — اضبط PUBLIC_BASE_URL في إعدادات النشر.",
        }
    msg = _build_task_wa_message(task, kind=kind)
    label = "فتح صفحة الرد" if kind == "assigned" else "إعادة إرسال الرد"
    ok = _send_whatsapp_link(phone, msg, link, link_label=label)
    if not ok:
        return {
            "ok": False,
            "error": "فشل الإرسال — تحقق من اتصال واتساب في شاشة الإعدادات.",
        }
    return {"ok": True, "link": link, "phone": phone}


def schedule_task_assigned(task_id: int, public_link: str = "") -> None:
    def _run():
        from ops.models import Task

        task = Task.objects.select_related("assigned_to", "created_by").filter(pk=task_id).first()
        if not task or not task.assigned_to_id:
            return
        result = send_task_link_now(task, public_link=public_link, kind="assigned")
        if not result.get("ok"):
            logger.warning("Task %s WhatsApp: %s", task_id, result.get("error"))

    _run_in_background(f"task-assign-{task_id}", _run)


def schedule_task_submitted(task_id: int) -> None:
    def _run():
        from ops.models import Task

        task = Task.objects.select_related("assigned_to", "created_by").filter(pk=task_id).first()
        if not task:
            return
        try:
            pdf_bytes, filename = build_task_pdf(task, actor=task.assigned_to)
        except Exception:
            logger.exception("PDF build failed for task submit %s", task_id)
            return
        msg = _pdf_caption(
            "إشعار رد مهمة",
            instruction="نُرفق ملف الرد. يرجى المراجعة والاعتماد.",
        )
        _notify_pdf_to_roles(
            msg,
            pdf_bytes=pdf_bytes,
            filename=filename,
            pdf_url="",
            roles=get_user_model().NOTIFY_ROLES,
        )
        if task.created_by_id and getattr(task.created_by, "whatsapp", ""):
            _notify_pdf_to_user(
                task.created_by,
                msg,
                pdf_bytes=pdf_bytes,
                filename=filename,
                pdf_url="",
            )

    _run_in_background(f"task-submit-{task_id}", _run)


def schedule_task_review_result(task_id: int, approved: bool) -> None:
    def _run():
        from ops.models import Task

        task = Task.objects.select_related("assigned_to", "reviewed_by").filter(pk=task_id).first()
        if not task or not task.assigned_to_id:
            return
        if not approved:
            task.ensure_public_token()
            if not task.public_token:
                task.save(update_fields=["public_token"])
            link = _task_public_url(task)
            result = send_task_link_now(task, public_link=link, kind="correction")
            if not result.get("ok"):
                logger.warning(
                    "Failed to send task correction link for task %s: %s",
                    task_id,
                    result.get("error"),
                )
            return
        try:
            pdf_bytes, filename = build_task_pdf(task, actor=task.reviewed_by)
        except Exception:
            logger.exception("PDF build failed for task review %s", task_id)
            return
        msg = _pdf_caption(
            "إشعار اعتماد مهمة",
            instruction="نُرفق ملف المهمة المعتمدة.",
        )
        _notify_pdf_to_user(
            task.assigned_to,
            msg,
            pdf_bytes=pdf_bytes,
            filename=filename,
            pdf_url="",
        )

    _run_in_background(f"task-review-{task_id}", _run)


def schedule_return_authorized(item_id: int, actor_id: int) -> None:
    """After representative authorizes → notify receiver, accountant, ops, dept head."""

    def _run():
        from ops.models import ReturnRequest

        User = get_user_model()
        ret = (
            ReturnRequest.objects.select_related(
                "batch", "representative", "rep_decided_by", "created_by"
            )
            .filter(pk=item_id)
            .first()
        )
        actor = User.objects.filter(pk=actor_id).first()
        if not ret or not actor or not ret.batch_id:
            return
        _notify_return_rep_decision(ret.batch, [ret], actor=actor, decision="authorized")

    _run_in_background(f"return-authorize-{item_id}", _run)


def schedule_return_rep_rejected(item_id: int, actor_id: int) -> None:
    """After representative rejects → notify receiver, accountant, ops, dept head."""

    def _run():
        from ops.models import ReturnRequest

        User = get_user_model()
        ret = (
            ReturnRequest.objects.select_related(
                "batch", "representative", "rep_decided_by", "created_by"
            )
            .filter(pk=item_id)
            .first()
        )
        actor = User.objects.filter(pk=actor_id).first()
        if not ret or not actor or not ret.batch_id:
            return
        _notify_return_rep_decision(ret.batch, [ret], actor=actor, decision="rejected")

    _run_in_background(f"return-rep-reject-{item_id}", _run)


def schedule_return_batch_rep_decision(
    batch_id: int, actor_id: int, decision: str, item_ids: list[int] | None = None
) -> None:
    """Batch-level rep authorize/reject — one WhatsApp+PDF per action."""

    def _run():
        from ops.models import ReturnRequest

        User = get_user_model()
        batch = (
            ReturnBatch.objects.select_related("representative", "created_by")
            .prefetch_related("items")
            .filter(pk=batch_id)
            .first()
        )
        actor = User.objects.filter(pk=actor_id).first()
        if not batch or not actor:
            return
        qs = batch.items.all()
        if item_ids:
            qs = qs.filter(pk__in=item_ids)
        items = list(qs)
        if not items:
            return
        _notify_return_rep_decision(batch, items, actor=actor, decision=decision)

    _run_in_background(f"return-batch-{decision}-{batch_id}", _run)


def _notify_return_rep_decision(batch, items, *, actor, decision: str) -> dict:
    """
    decision: 'authorized' | 'rejected'
    Notifies: receiver, accountant, operations, dept head (+ PDF).
    """
    User = get_user_model()
    if decision not in ("authorized", "rejected"):
        return {"sent": 0, "total": 0, "phones": [], "error": "قرار غير معروف."}

    try:
        pdf_bytes, filename = build_return_batch_pdf(batch)
    except Exception:
        logger.exception("PDF build failed for return rep decision batch %s", batch.pk)
        return {"sent": 0, "total": 0, "phones": [], "error": "تعذّر إنشاء PDF."}

    batch.ensure_public_token()
    if not batch.public_token:
        batch.save(update_fields=["public_token"])
    pdf_url = _return_pdf_url(batch)

    if decision == "authorized":
        title = "إشعار تعميد مرتجع"
        instruction = "نُرفق ملف المرتجع بعد تعميد المندوب. يرجى متابعة الإجراء."
    else:
        title = "إشعار رفض مرتجع"
        instruction = "نُرفق ملف المرتجع. يرجى الاطلاع والمتابعة."

    body = _pdf_caption(title, instruction=instruction)

    result = _notify_pdf_to_roles(
        body,
        pdf_bytes=pdf_bytes,
        filename=filename,
        pdf_url=pdf_url,
        roles=User.RETURN_AUTHORIZE_NOTIFY_ROLES,
    )
    if result.get("error"):
        logger.warning(
            "Return rep %s notify failed for batch %s: %s",
            decision,
            batch.pk,
            result.get("error"),
        )
    return result


def schedule_daily_distribution_notify(row_ids: list[int], actor_id: int) -> None:
    """After saving daily supply distribution → PDF + notify accountant, ops, receiver."""

    def _run():
        from ops.models import DailySupplyDistribution

        User = get_user_model()
        actor = User.objects.filter(pk=actor_id).first()
        rows = list(
            DailySupplyDistribution.objects.select_related("created_by")
            .filter(pk__in=row_ids)
            .order_by("pk")
        )
        if not rows or not actor:
            return

        batch_ref = rows[0].batch_number or f"DIST-{rows[0].pk}"
        token = _sync_batch_token(
            DailySupplyDistribution,
            batch_number=rows[0].batch_number or "",
            pks=row_ids,
        )
        try:
            pdf_bytes, filename = build_distribution_batch_pdf(rows, actor=actor)
        except Exception:
            logger.exception("PDF build failed for distribution %s", row_ids)
            return

        pdf_url = _public_pdf_url("ops:distribution_batch_pdf_public_file", token)
        msg = _pdf_caption(
            "إشعار توزيع يومي",
            instruction="نُرفق ملف التوزيع. يرجى المراجعة والتنفيذ.",
        )
        result = _notify_pdf_to_roles(
            msg,
            pdf_bytes=pdf_bytes,
            filename=filename,
            pdf_url=pdf_url,
            roles=User.RETURN_AUTHORIZE_NOTIFY_ROLES,
        )
        if result.get("error"):
            logger.warning(
                "Daily distribution notify failed for %s: %s",
                row_ids,
                result.get("error"),
            )

    _run_in_background(f"dist-{row_ids[:1]}", _run)


def schedule_variance_authorized(variance_id: int, actor_id: int) -> None:
    """After receiver authorizes shortage/excess → PDF + WhatsApp supplier."""

    def _run():
        from ops.models import DistributionVariance, Supplier

        User = get_user_model()
        row = DistributionVariance.objects.filter(pk=variance_id).first()
        actor = User.objects.filter(pk=actor_id).first()
        if not row or not actor:
            return

        rows = list(
            DistributionVariance.objects.filter(batch_number=row.batch_number).order_by("pk")
            if row.batch_number
            else [row]
        )
        token = _sync_batch_token(
            DistributionVariance,
            batch_number=row.batch_number or "",
            pks=[r.pk for r in rows],
        )
        try:
            pdf_bytes, filename = build_variance_batch_pdf(rows, actor=actor)
        except Exception:
            logger.exception("PDF build failed for variance %s", variance_id)
            return

        pdf_url = _public_pdf_url("ops:variance_batch_pdf_public_file", token)
        batch_ref = row.batch_number or f"VAR-{row.pk}"
        msg = _pdf_caption(
            "إشعار فروقات توزيع",
            instruction="نُرفق ملف الفروقات المعتمد. يرجى المراجعة والتنسيق.",
        )

        supplier = Supplier.objects.filter(name=row.supplier).first()
        phone = supplier.normalized_phone() if supplier else ""
        extra = []
        if phone:
            extra.append({
                "phone": phone,
                "label": f"مورد — {row.supplier}",
                "role": "supplier",
                "message": msg,
            })
        else:
            logger.warning(
                "No supplier WhatsApp for variance %s (supplier=%s)",
                variance_id,
                row.supplier,
            )

        result = _notify_pdf_to_roles(
            msg,
            pdf_bytes=pdf_bytes,
            filename=filename,
            pdf_url=pdf_url,
            roles=User.RETURN_AUTHORIZE_NOTIFY_ROLES,
            extra=extra,
        )
        if result.get("error"):
            logger.warning(
                "Variance notify failed for %s: %s",
                variance_id,
                result.get("error"),
            )

    _run_in_background(f"variance-auth-{variance_id}", _run)


def schedule_daily_order_approved(order_id: int, actor_id: int) -> None:
    """Send purchase-order PDF to supplier via WhatsApp after approval (like returns)."""

    def _run():
        from ops.models import DailyOrder, Supplier

        User = get_user_model()
        seed = (
            DailyOrder.objects.select_related("representative", "reviewed_by", "created_by")
            .filter(pk=order_id)
            .first()
        )
        actor = User.objects.filter(pk=actor_id).first()
        if not seed or not actor:
            return

        if seed.batch_number:
            orders = list(
                DailyOrder.objects.select_related("representative", "reviewed_by", "created_by")
                .filter(batch_number=seed.batch_number)
                .order_by("pk")
            )
        else:
            orders = [seed]

        # Prefer approved lines in the file; fall back to all
        approved = [o for o in orders if o.status == DailyOrder.Status.APPROVED]
        orders = approved or orders

        for o in orders:
            o.ensure_public_token()
            if not o.public_token:
                o.save(update_fields=["public_token"])
        # Keep one shared token across the batch for a stable public URL
        token = orders[0].public_token
        if seed.batch_number and token:
            DailyOrder.objects.filter(batch_number=seed.batch_number).exclude(
                public_token=token
            ).update(public_token=token)

        try:
            pdf_bytes, filename = build_daily_orders_pdf(orders, actor=actor)
        except Exception:
            logger.exception("PDF build failed for daily order %s", seed.order_number)
            return

        pdf_url = _daily_order_pdf_url(token)
        batch_ref = seed.batch_number or seed.order_number
        msg = _pdf_caption(
            "أمر شراء معتمد",
            instruction="نُرفق ملف الطلبية. يرجى التنفيذ وفق البيانات الواردة.",
        )

        supplier = Supplier.objects.filter(name=seed.supplier).first()
        phone = supplier.normalized_phone() if supplier else ""
        recipients = []
        if phone:
            recipients.append(
                {
                    "phone": phone,
                    "label": f"مورد — {seed.supplier}",
                    "role": "supplier",
                    "message": msg,
                }
            )
        else:
            logger.info(
                "No supplier WhatsApp for daily order batch %s (supplier=%s)",
                batch_ref,
                seed.supplier,
            )

        for entry in collect_recipient_entries(include_roles=True):
            recipients.append({**entry, "message": msg})

        if not recipients:
            return

        result = notify_with_pdf(
            message=msg,
            pdf_bytes=pdf_bytes,
            filename=filename,
            recipients=recipients,
            media_url=pdf_url,
        )
        if result.get("error"):
            logger.warning(
                "Daily order PDF WhatsApp issue for %s: %s",
                batch_ref,
                result.get("error"),
            )

    _run_in_background(f"daily-order-approved-{order_id}", _run)


def _daily_order_pdf_url(token: str, request=None) -> str:
    path = reverse(
        "ops:daily_order_pdf_public_file",
        kwargs={"token": token},
    )
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    if base:
        return f"{base}{path}"
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def schedule_supply_batch_status(seed_pk: int, actor_id: int, status: str) -> None:
    """إكمال/رفض ملف توريد → PDF + إشعار."""

    def _run():
        from ops.models import SupplyOrder

        User = get_user_model()
        actor = User.objects.filter(pk=actor_id).first()
        seed = SupplyOrder.objects.select_related("representative", "created_by").filter(pk=seed_pk).first()
        if not seed or not actor:
            return
        if seed.batch_number:
            orders = list(
                SupplyOrder.objects.filter(batch_number=seed.batch_number).order_by("pk")
            )
        else:
            orders = [seed]
        if not orders:
            return

        token = _sync_batch_token(
            SupplyOrder,
            batch_number=seed.batch_number or "",
            pks=[o.pk for o in orders],
        )
        try:
            pdf_bytes, filename = build_supply_orders_pdf(orders, actor=actor)
        except Exception:
            logger.exception("PDF build failed for supply status %s", seed_pk)
            return

        pdf_url = _public_pdf_url("ops:supply_batch_pdf_public_file", token)
        batch_ref = seed.batch_number or seed.order_number
        title = "إشعار إكمال توريد" if status == "completed" else "إشعار رفض توريد"
        instruction = (
            "نُرفق ملف التوريد المعتمد."
            if status == "completed"
            else "نُرفق ملف التوريد. يرجى الاطلاع."
        )
        msg = _pdf_caption(title, instruction=instruction)
        _notify_pdf_to_roles(
            msg,
            pdf_bytes=pdf_bytes,
            filename=filename,
            pdf_url=pdf_url,
            roles=User.NOTIFY_ROLES,
        )

    _run_in_background(f"supply-status-{seed_pk}-{status}", _run)


def schedule_return_ops_batch_decision(
    batch_id: int, actor_id: int, decision: str, item_ids: list[int] | None = None
) -> None:
    """اعتماد/رفض العمليات لملف مرتجع → PDF + إشعار."""

    def _run():
        from ops.models import ReturnBatch

        User = get_user_model()
        actor = User.objects.filter(pk=actor_id).first()
        batch = (
            ReturnBatch.objects.select_related("representative")
            .prefetch_related("items")
            .filter(pk=batch_id)
            .first()
        )
        if not batch or not actor:
            return

        if item_ids:
            items = list(batch.items.filter(pk__in=item_ids))
        else:
            items = list(batch.items.all())
        try:
            pdf_bytes, filename = build_return_batch_pdf(batch)
        except Exception:
            logger.exception("PDF build failed for return ops %s", batch_id)
            return

        pdf_url = _return_pdf_url(batch)
        title = (
            "إشعار اعتماد مرتجع"
            if decision == "accepted"
            else "إشعار رفض مرتجع"
        )
        instruction = (
            "نُرفق ملف المرتجع بعد اعتماد العمليات."
            if decision == "accepted"
            else "نُرفق ملف المرتجع. يرجى الاطلاع."
        )
        msg = _pdf_caption(title, instruction=instruction)
        _notify_pdf_to_roles(
            msg,
            pdf_bytes=pdf_bytes,
            filename=filename,
            pdf_url=pdf_url,
            roles=User.RETURN_AUTHORIZE_NOTIFY_ROLES,
        )

    _run_in_background(f"return-ops-{decision}-{batch_id}", _run)
