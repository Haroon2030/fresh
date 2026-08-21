"""Structured WhatsApp+PDF notifications for ops documents."""
from __future__ import annotations

import logging
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone

from ops.pdf_docs import build_daily_orders_pdf, build_return_batch_pdf, build_supply_orders_pdf, role_label
from ops.whatsapp import (
    collect_recipient_entries,
    notify_with_pdf,
    normalize_whatsapp,
)
from ops.models import ReturnBatch, WhatsAppRoleContact


def _user_phone(user) -> str:
    if not user:
        return ""
    return normalize_whatsapp(getattr(user, "whatsapp", "") or "")


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
        return f"الرابط: {base}"
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
    return f"{user.display_name} | الدور: {role_label(user)}"


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
    items = list(batch.items.all())
    item_lines = []
    for i, it in enumerate(items[:12], 1):
        item_lines.append(
            f"  {i}. {it.item_name} × {it.quantity} — {it.get_return_type_display()}"
        )
    if len(items) > 12:
        item_lines.append(f"  … و{len(items) - 12} أصناف أخرى")

    follow_msg = "\n".join(
        [
            "════════════════════",
            "عمليات الفرش | مرتجع جديد — للمتابعة",
            "════════════════════",
            "تم حفظ مرتجع بانتظار تعميد المندوب.",
            f"رقم الملف: {batch.return_number}",
            f"الفرع: {batch.branch}",
            f"الأصناف: {len(items)}",
            f"المندوب المسؤول: {batch.representative.display_name} | {role_label(batch.representative)}",
            f"المرسل: {_actor_line(actor)}",
            f"وقت الحفظ: {_now_str()}",
            "────────────────────",
            "ملخص الأصناف:",
            *(item_lines or ["  —"]),
            "────────────────────",
            "المطلوب من العمليات والمحاسب: المتابعة حتى اكتمال التعميد والقبول.",
            "📄 ملف PDF للتحميل:",
            pdf_url,
            "════════════════════",
        ]
    )

    rep_msg = "\n".join(
        [
            "════════════════════",
            "عمليات الفرش | تنبيه للمندوب — مطلوب التعميد",
            "════════════════════",
            "يوجد مرتجع جديد يحتاج تعميدك قبل متابعة العمليات.",
            f"رقم الملف: {batch.return_number}",
            f"الفرع: {batch.branch}",
            f"عدد الأصناف: {len(items)}",
            f"المرسل: {_actor_line(actor)}",
            f"وقت الحفظ: {_now_str()}",
            "────────────────────",
            "المطلوب منك:",
            "1) تحميل ملف PDF ومراجعته",
            "2) تعميد أو رفض كل صنف",
            "3) بعد التعميد يصل إشعار للمحاسب والمستلم والعمليات",
            "────────────────────",
            "📄 تحميل ملف المرتجع PDF:",
            pdf_url,
            "════════════════════",
        ]
    )

    # العمليات + المحاسب للمتابعة (قبل التعميد)
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
        # نفس الرقم في قائمة المتابعة — فضّل رسالة التعميد للمندوب
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
    try:
        pdf_bytes, filename = build_supply_orders_pdf(orders, actor=actor)
    except Exception:
        logger.exception("PDF build failed for supply")
        return {"sent": 0, "total": 0, "phones": [], "error": "تعذّر إنشاء PDF للتوريد."}

    nums = [o.order_number for o in orders]
    lines = [
        f"  • {o.order_number}: {o.item_name} × {o.quantity}" for o in orders[:12]
    ]
    if len(orders) > 12:
        lines.append(f"  … و{len(orders) - 12} أخرى")

    msg = "\n".join(
        [
            "════════════════════",
            "عمليات الفرش | إشعار تشغيلي",
            "النوع: طلبات توريد جديدة",
            "════════════════════",
            f"الأرقام: {', '.join(nums)}",
            f"العدد: {len(orders)}",
            f"المندوب: {representative.display_name} | {role_label(representative)}",
            f"المرسل: {_actor_line(actor)}",
            f"وقت الحفظ: {_now_str()}",
            "────────────────────",
            "التفاصيل:",
            *lines,
            "────────────────────",
            "المرفق: ملف PDF رسمي",
            _portal_hint(),
            "════════════════════",
        ]
    )

    recipients = collect_recipient_entries(include_roles=True)
    rep_phone = _user_phone(representative) or _role_contact_phone("representative")
    if rep_phone and not any(r["phone"] == rep_phone for r in recipients):
        recipients.append(
            {
                "phone": rep_phone,
                "label": f"{representative.display_name} — {role_label(representative)}",
                "role": "representative",
                "user_id": getattr(representative, "pk", None),
            }
        )

    return notify_with_pdf(
        message=msg,
        pdf_bytes=pdf_bytes,
        filename=filename,
        recipients=recipients,
    )


def _task_public_url(task) -> str:
    path = reverse("ops:task_public", kwargs={"token": task.public_token})
    base = getattr(settings, "PUBLIC_BASE_URL", "") or ""
    if base:
        return f"{base.rstrip('/')}{path}"
    return path


def schedule_task_assigned(task_id: int) -> None:
    def _run():
        from ops.models import Task
        from ops.whatsapp import notify_user

        task = Task.objects.select_related("assigned_to", "created_by").filter(pk=task_id).first()
        if not task or not task.assigned_to_id:
            return
        link = _task_public_url(task)
        body = "\n".join([
            f"المهمة: {task.title}",
            f"الفرع: {task.branch or '—'}",
            f"تفاصيل الزيارة:\n{task.visit_details or task.description or '—'}",
            f"الأولوية: {task.get_priority_display()}",
            "",
            "افتح الرابط للرد (نص + صور) وإرسال المهمة للمراجعة:",
            link,
        ])
        notify_user(task.assigned_to, "مهمة جديدة مُسندة إليك", body)

    _run_in_background(f"task-assign-{task_id}", _run)


def schedule_task_submitted(task_id: int) -> None:
    def _run():
        from ops.models import Task
        from ops.whatsapp import notify_roles, notify_user

        task = Task.objects.select_related("assigned_to", "created_by").filter(pk=task_id).first()
        if not task:
            return
        link = _task_public_url(task)
        body = "\n".join([
            f"المهمة: {task.title}",
            f"الفرع: {task.branch or '—'}",
            f"الموظف: {task.assigned_to.display_name if task.assigned_to_id else '—'}",
            f"الرد:\n{(task.response_text or '—')[:500]}",
            f"الصور: {task.response_photos.count()}",
            "",
            "راجع الرد من لوحة المهام (عمود بانتظار المراجعة).",
            f"رابط المهمة: {link}",
        ])
        notify_roles("رد مهمة بانتظار مراجعتك", body)
        if task.created_by_id and getattr(task.created_by, "whatsapp", ""):
            notify_user(task.created_by, "رد مهمة بانتظار مراجعتك", body)

    _run_in_background(f"task-submit-{task_id}", _run)


def schedule_task_review_result(task_id: int, approved: bool) -> None:
    def _run():
        from ops.models import Task
        from ops.whatsapp import notify_user

        task = Task.objects.select_related("assigned_to", "reviewed_by").filter(pk=task_id).first()
        if not task or not task.assigned_to_id:
            return
        link = _task_public_url(task)
        if approved:
            title = "تم اعتماد رد المهمة وإغلاقها"
            body = "\n".join([
                f"المهمة: {task.title}",
                f"الفرع: {task.branch or '—'}",
                f"ملاحظة المراجع: {task.review_note or '—'}",
            ])
        else:
            title = "رُدّت المهمة — مطلوب تصحيح"
            body = "\n".join([
                f"المهمة: {task.title}",
                f"الفرع: {task.branch or '—'}",
                f"ملاحظة المراجع: {task.review_note or '—'}",
                "",
                "افتح الرابط وعدّل الرد ثم أعد الإرسال:",
                link,
            ])
        notify_user(task.assigned_to, title, body)

    _run_in_background(f"task-review-{task_id}", _run)


def schedule_return_authorized(item_id: int, actor_id: int) -> None:
    """After representative authorizes a return item → notify ops, accountant, receiver."""

    def _run():
        from ops.models import ReturnRequest
        from ops.whatsapp import notify_roles

        User = get_user_model()
        ret = (
            ReturnRequest.objects.select_related(
                "batch", "representative", "rep_decided_by", "created_by"
            )
            .filter(pk=item_id)
            .first()
        )
        actor = User.objects.filter(pk=actor_id).first()
        if not ret or not actor:
            return

        batch_no = ret.return_number or (
            ret.batch.return_number if ret.batch_id else "—"
        )
        body = "\n".join(
            [
                "════════════════════",
                "عمليات الفرش | تعميد مندوب",
                "════════════════════",
                f"رقم الملف: {batch_no}",
                f"الصنف: {ret.item_name}",
                f"رقم الصنف: {ret.item_number or '—'}",
                f"الكمية: {ret.quantity}",
                f"النوع: {ret.get_return_type_display()}",
                f"الفرع: {ret.batch.branch if ret.batch_id else '—'}",
                f"المندوب: {ret.representative.display_name}",
                f"عمّد بواسطة: {_actor_line(actor)}",
                f"الوقت: {_now_str()}",
                "────────────────────",
                "المطلوب: متابعة القبول/الرفض من العمليات بعد التعميد.",
                "════════════════════",
            ]
        )
        result = notify_roles(
            "تعميد مرتجع — للمحاسب والمستلم والعمليات",
            body,
            roles=User.RETURN_AUTHORIZE_NOTIFY_ROLES,
        )
        if result.get("error"):
            logger.warning(
                "Return authorize notify failed for item %s: %s",
                item_id,
                result.get("error"),
            )

    _run_in_background(f"return-authorize-{item_id}", _run)


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
        item_lines = [
            f"  {i}. {o.item_name} × {o.quantity} — السعر {o.unit_price}"
            for i, o in enumerate(orders[:12], 1)
        ]
        if len(orders) > 12:
            item_lines.append(f"  … و{len(orders) - 12} أصناف أخرى")

        msg = "\n".join(
            [
                "════════════════════",
                "عمليات الفرش | طلب شراء معتمد",
                "════════════════════",
                f"رقم الملف: {batch_ref}",
                f"التاريخ: {seed.order_date}",
                f"الفرع: {seed.branch}",
                f"المورد: {seed.supplier or '—'}",
                f"المندوب: {seed.representative.display_name}",
                f"الأصناف: {len(orders)}",
                f"اعتمد بواسطة: {_actor_line(actor)}",
                f"وقت الاعتماد: {_now_str()}",
                "────────────────────",
                "ملخص الأصناف:",
                *(item_lines or ["  —"]),
                "────────────────────",
                "📄 ملف PDF للتحميل:",
                pdf_url,
                "════════════════════",
            ]
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

        # Also notify ops roles (same pattern as returns staff list)
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
