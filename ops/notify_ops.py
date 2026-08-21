"""Structured WhatsApp+PDF notifications for ops documents."""
from __future__ import annotations

import logging
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone

from ops.pdf_docs import build_return_batch_pdf, build_supply_orders_pdf, role_label
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
    On saving a return file:
    - PDF document via WhatsApp + download link
    - Dedicated action message+PDF to the representative
    """
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

    staff_msg = "\n".join(
        [
            "════════════════════",
            "عمليات الفرش | إشعار تشغيلي",
            "النوع: ملف مرتجع جديد",
            "════════════════════",
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
            "📄 ملف PDF للتحميل:",
            pdf_url,
            "════════════════════",
        ]
    )

    rep_msg = "\n".join(
        [
            "════════════════════",
            "عمليات الفرش | تنبيه للمندوب",
            "════════════════════",
            "يوجد مردود جديد يجب متابعته واعتماده، ويجب الرد.",
            f"رقم الملف: {batch.return_number}",
            f"الفرع: {batch.branch}",
            f"عدد الأصناف: {len(items)}",
            f"المرسل: {_actor_line(actor)}",
            f"وقت الحفظ: {_now_str()}",
            "────────────────────",
            "المطلوب منك:",
            "1) تحميل ملف PDF ومراجعته",
            "2) تعميد أو رفض كل صنف",
            "3) الرد والمتابعة حتى الإغلاق",
            "────────────────────",
            "📄 تحميل ملف المرتجع PDF:",
            pdf_url,
            "════════════════════",
        ]
    )

    recipients = collect_recipient_entries(include_roles=True)
    rep = batch.representative
    rep_phone = _user_phone(rep) or _role_contact_phone("representative")

    # One bubble per unique phone: PDF + caption (no separate text message)
    enriched = []
    seen = set()
    for entry in recipients:
        phone = entry.get("phone") or ""
        if not phone or phone in seen:
            continue
        seen.add(phone)
        # Representative gets the action-focused caption on the same PDF
        msg = rep_msg if phone == rep_phone else staff_msg
        enriched.append({**entry, "message": msg})

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

    result = notify_with_pdf(
        message=staff_msg,
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


def schedule_daily_order_approved(order_id: int, actor_id: int) -> None:
    """Notify supplier via WhatsApp after a daily purchase order is approved."""

    def _run():
        from ops.models import DailyOrder, Supplier
        from ops.whatsapp import send_text

        User = get_user_model()
        order = (
            DailyOrder.objects.select_related("representative", "reviewed_by")
            .filter(pk=order_id)
            .first()
        )
        actor = User.objects.filter(pk=actor_id).first()
        if not order or not actor:
            return

        supplier = Supplier.objects.filter(name=order.supplier).first()
        phone = supplier.normalized_phone() if supplier else ""
        if not phone:
            logger.info(
                "No supplier WhatsApp for daily order %s (supplier=%s)",
                order.order_number,
                order.supplier,
            )
            return

        msg = "\n".join(
            [
                "════════════════════",
                "عمليات الفرش | طلب شراء معتمد",
                "════════════════════",
                f"رقم الطلبية: {order.order_number}",
                f"التاريخ: {order.order_date}",
                f"الفرع: {order.branch}",
                f"المندوب: {order.representative.display_name}",
                "────────────────────",
                f"الصنف: {order.item_name}",
                f"رقم الصنف: {order.item_number or '—'}",
                f"الكمية: {order.quantity}",
                f"السعر: {order.unit_price}",
                "────────────────────",
                f"اعتمد بواسطة: {actor.display_name}",
                f"وقت الاعتماد: {_now_str()}",
                "════════════════════",
            ]
        )
        ok = send_text(phone, msg)
        if not ok:
            logger.warning(
                "Failed WhatsApp to supplier %s for order %s",
                phone,
                order.order_number,
            )

    _run_in_background(f"daily-order-approved-{order_id}", _run)
