from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Max, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms import TaskForm
from .models import (
    Branch,
    CatalogItem,
    DailyOrder,
    ReturnBatch,
    ReturnRequest,
    SupplyOrder,
    Supplier,
    Task,
    TaskResponsePhoto,
    WhatsAppRoleContact,
)
from .pdf_docs import build_daily_orders_pdf, build_return_batch_pdf
from .whatsapp import (
    collect_notify_phones,
    connection_state,
    fetch_qr,
    logout_instance,
    recreate_instance,
    normalize_whatsapp,
    notify_roles,
    resolve_instance_name,
    send_test_to_roles,
)
from .notify_ops import (
    schedule_daily_order_approved,
    schedule_return_authorized,
    schedule_return_notify,
    schedule_supply_notify,
    schedule_task_assigned,
    schedule_task_review_result,
    schedule_task_submitted,
)

User = get_user_model()


def manager_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_manager:
            messages.error(request, 'هذه العملية متاحة لمدير العمليات فقط.')
            return redirect('ops:supply')
        return view_func(request, *args, **kwargs)
    return wrapper


def _supply_queryset(user):
    qs = SupplyOrder.objects.select_related('representative', 'created_by', 'reviewed_by')
    if user.is_representative:
        qs = qs.filter(representative=user)
    return qs


def _return_batch_queryset(user):
    qs = ReturnBatch.objects.select_related('representative', 'created_by').prefetch_related('items')
    if user.is_representative:
        qs = qs.filter(representative=user)
    return qs


def _return_item_or_404(pk):
    return get_object_or_404(
        ReturnRequest.objects.select_related('batch', 'representative'),
        pk=pk,
    )


def _redirect_returns(batch_id=None):
    url = reverse('ops:returns')
    if batch_id:
        return redirect(f'{url}?open={batch_id}')
    return redirect(url)


def _greeting_for(now):
    hour = now.hour
    if 5 <= hour < 12:
        return 'صباح الخير'
    if 12 <= hour < 17:
        return 'مساء الخير'
    if 17 <= hour < 22:
        return 'مساء النور'
    return 'أهلاً بك'


@login_required
def dashboard(request):
    user = request.user
    now = timezone.localtime()

    supply_qs = _supply_queryset(user)
    returns_qs = _return_batch_queryset(user)
    tasks_qs = _task_queryset(user)

    supply_total = supply_qs.count()
    supply_pending = supply_qs.filter(status=SupplyOrder.Status.PENDING).count()
    supply_completed = supply_qs.filter(status=SupplyOrder.Status.COMPLETED).count()
    supply_rejected = supply_qs.filter(status=SupplyOrder.Status.REJECTED).count()

    returns_total = returns_qs.count()
    return_items = ReturnRequest.objects.filter(batch__in=returns_qs)
    returns_pending = return_items.filter(status=ReturnRequest.Status.PENDING).count()
    returns_accepted = return_items.filter(status=ReturnRequest.Status.ACCEPTED).count()
    returns_rejected = return_items.filter(status=ReturnRequest.Status.REJECTED).count()

    tasks_todo = tasks_qs.filter(status=Task.Status.TODO).count()
    tasks_progress = tasks_qs.filter(status=Task.Status.IN_PROGRESS).count()
    tasks_review = tasks_qs.filter(status=Task.Status.PENDING_REVIEW).count()
    tasks_done = tasks_qs.filter(status=Task.Status.DONE).count()
    tasks_total = tasks_todo + tasks_progress + tasks_review + tasks_done

    items_total = CatalogItem.objects.count()
    users_total = User.objects.filter(is_active=True).count() if user.is_manager else None

    day_labels = []
    supply_series = []
    returns_series = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).date()
        day_labels.append(day.strftime('%d/%m'))
        supply_series.append(supply_qs.filter(created_at__date=day).count())
        returns_series.append(returns_qs.filter(created_at__date=day).count())

    charts = {
        'week': {
            'labels': day_labels,
            'supply': supply_series,
            'returns': returns_series,
        },
        'supply_status': {
            'labels': ['قيد الانتظار', 'مكتمل', 'مرفوض'],
            'values': [supply_pending, supply_completed, supply_rejected],
        },
        'tasks_status': {
            'labels': ['انتظار', 'تنفيذ', 'مراجعة', 'مكتمل'],
            'values': [tasks_todo, tasks_progress, tasks_review, tasks_done],
        },
    }

    recent_supply = supply_qs.order_by('-created_at')[:5]
    recent_tasks = tasks_qs.select_related('assigned_to').order_by('-created_at')[:5]

    return render(request, 'ops/dashboard.html', {
        'active_nav': 'dashboard',
        'greeting': _greeting_for(now),
        'today_label': now.strftime('%Y/%m/%d'),
        'weekday_ar': [
            'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد',
        ][now.weekday()],
        'stats': {
            'supply_total': supply_total,
            'supply_pending': supply_pending,
            'returns_total': returns_total,
            'returns_pending': returns_pending,
            'tasks_total': tasks_total,
            'tasks_open': tasks_todo + tasks_progress + tasks_review,
            'items_total': items_total,
            'users_total': users_total,
            'returns_accepted': returns_accepted,
            'returns_rejected': returns_rejected,
        },
        'charts': charts,
        'recent_supply': recent_supply,
        'recent_returns': returns_qs.prefetch_related('items').order_by('-created_at')[:5],
        'recent_tasks': recent_tasks,
    })


def _task_queryset(user):
    qs = Task.objects.select_related('assigned_to', 'created_by')
    if user.is_representative:
        qs = qs.filter(assigned_to=user)
    return qs


@login_required
def supply_list(request):
    from django.contrib.auth import get_user_model
    User = get_user_model()

    qs = _supply_queryset(request.user)

    status = request.GET.get('status', '')
    period = request.GET.get('period', 'all')

    if status in dict(SupplyOrder.Status.choices):
        qs = qs.filter(status=status)

    now = timezone.now()
    if period == 'week':
        qs = qs.filter(created_at__gte=now - timedelta(days=7))
    elif period == 'month':
        qs = qs.filter(created_at__gte=now - timedelta(days=30))
    elif period == 'quarter':
        qs = qs.filter(created_at__gte=now - timedelta(days=90))

    all_qs = _supply_queryset(request.user)
    total_orders = all_qs.count()
    pending_count = all_qs.filter(status=SupplyOrder.Status.PENDING).count()
    completed = all_qs.filter(status=SupplyOrder.Status.COMPLETED)
    spent = Decimal('0')
    for order in completed:
        spent += order.total_amount
    budget_cap = Decimal('65000')
    budget_pct = min(100, int((spent / budget_cap) * 100)) if budget_cap else 0

    paginator = Paginator(qs, 10)
    page = paginator.get_page(request.GET.get('page'))

    reps = User.objects.filter(role=User.Role.REPRESENTATIVE, is_active=True)
    if not reps.exists():
        representatives = User.objects.filter(is_active=True).order_by('first_name', 'username')
    else:
        representatives = reps.order_by('first_name', 'username')

    return render(request, 'ops/supply.html', {
        'orders': page,
        'page_obj': page,
        'representatives': representatives,
        'status_filter': status,
        'period_filter': period,
        'total_orders': total_orders,
        'pending_count': pending_count,
        'budget_spent': spent,
        'budget_pct': budget_pct,
        'active_nav': 'supply',
    })


@login_required
@require_POST
def supply_create(request):
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if request.user.is_representative:
        representative = request.user
    else:
        rep_id = request.POST.get('representative')
        representative = User.objects.filter(pk=rep_id, is_active=True).first()
        if not representative:
            messages.error(request, 'اختر المندوب أولاً.')
            return redirect('ops:supply')

    expected_raw = (request.POST.get('expected_date') or '').strip() or None
    item_names = request.POST.getlist('item_name')
    item_numbers = request.POST.getlist('item_number')
    units = request.POST.getlist('unit')
    packages = request.POST.getlist('package')
    quantities = request.POST.getlist('quantity')
    notes_list = request.POST.getlist('notes')

    created = []
    for i, item_name in enumerate(item_names):
        item_name = (item_name or '').strip()
        if not item_name:
            continue
        qty_raw = quantities[i] if i < len(quantities) else '1'
        try:
            quantity = max(1, int(qty_raw or 1))
        except (TypeError, ValueError):
            quantity = 1
        order = SupplyOrder(
            representative=representative,
            item_name=item_name,
            item_number=(item_numbers[i] if i < len(item_numbers) else '').strip(),
            unit=(units[i] if i < len(units) else '').strip(),
            package=(packages[i] if i < len(packages) else '').strip(),
            quantity=quantity,
            notes=(notes_list[i] if i < len(notes_list) else '').strip(),
            expected_date=expected_raw,
            created_by=request.user,
        )
        order.save()
        created.append(order)

    if created:
        if len(created) == 1:
            messages.success(request, f'تم إنشاء الطلب {created[0].order_number} بنجاح.')
        else:
            messages.success(request, f'تم إنشاء {len(created)} طلبات شراء بنجاح.')
        schedule_supply_notify(
            [o.pk for o in created],
            request.user.pk,
            representative.pk,
        )
        messages.info(request, 'جاري إرسال إشعار واتساب في الخلفية.')
    else:
        messages.error(request, 'أضف صفاً واحداً على الأقل مع الاسم.')
    return redirect('ops:supply')


@login_required
def supply_detail(request, pk):
    order = get_object_or_404(_supply_queryset(request.user), pk=pk)
    return render(request, 'ops/supply_detail.html', {
        'order': order,
        'active_nav': 'supply',
    })


@manager_required
@require_POST
def supply_complete(request, pk):
    order = get_object_or_404(SupplyOrder, pk=pk, status=SupplyOrder.Status.PENDING)
    order.status = SupplyOrder.Status.COMPLETED
    order.reviewed_by = request.user
    order.save(update_fields=['status', 'reviewed_by', 'updated_at'])
    messages.success(request, f'تم إكمال الطلب {order.order_number}.')
    notify_roles(
        'اكتمال توريد',
        f'{order.order_number} — {order.item_name}\n'
        f'بواسطة: {request.user.display_name}',
    )
    return redirect('ops:supply')


@manager_required
@require_POST
def supply_reject(request, pk):
    order = get_object_or_404(SupplyOrder, pk=pk, status=SupplyOrder.Status.PENDING)
    order.status = SupplyOrder.Status.REJECTED
    order.reviewed_by = request.user
    order.save(update_fields=['status', 'reviewed_by', 'updated_at'])
    messages.success(request, f'تم رفض الطلب {order.order_number}.')
    notify_roles(
        'رفض توريد',
        f'{order.order_number} — {order.item_name}\n'
        f'بواسطة: {request.user.display_name}',
    )
    return redirect('ops:supply')


@login_required
def returns_list(request):
    from django.contrib.auth import get_user_model
    User = get_user_model()

    qs = _return_batch_queryset(request.user)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(return_number__icontains=q)
            | Q(branch__icontains=q)
            | Q(representative__first_name__icontains=q)
            | Q(representative__last_name__icontains=q)
            | Q(representative__username__icontains=q)
            | Q(items__item_name__icontains=q)
            | Q(items__item_number__icontains=q)
            | Q(items__reason__icontains=q)
        ).distinct()

    reps = User.objects.filter(role=User.Role.REPRESENTATIVE, is_active=True)
    if not reps.exists():
        representatives = User.objects.filter(is_active=True).order_by('first_name', 'username')
    else:
        representatives = reps.order_by('first_name', 'username')

    open_batch = request.GET.get('open', '').strip()
    return render(request, 'ops/returns.html', {
        'batches': qs,
        'representatives': representatives,
        'branches': Branch.active_names(),
        'q': q,
        'open_batch': open_batch,
        'active_nav': 'returns',
        'return_types': ReturnRequest.ReturnType.choices,
    })


@login_required
@require_POST
def return_create(request):
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if request.user.is_representative:
        representative = request.user
    else:
        rep_id = request.POST.get('representative')
        representative = User.objects.filter(pk=rep_id, is_active=True).first()
        if not representative:
            messages.error(request, 'اختر المندوب أولاً.')
            return redirect('ops:returns')

    branch = (request.POST.get('branch') or '').strip()
    if not branch:
        messages.error(request, 'اختر الفرع.')
        return redirect('ops:returns')

    item_names = request.POST.getlist('item_name')
    item_numbers = request.POST.getlist('item_number')
    units = request.POST.getlist('unit')
    packages = request.POST.getlist('package')
    quantities = request.POST.getlist('quantity')
    return_types = request.POST.getlist('return_type')
    reasons = request.POST.getlist('reason')
    valid_types = dict(ReturnRequest.ReturnType.choices)

    rows = []
    for i, item_name in enumerate(item_names):
        item_name = (item_name or '').strip()
        reason = (reasons[i] if i < len(reasons) else '').strip()
        if not item_name or not reason:
            continue
        qty_raw = quantities[i] if i < len(quantities) else '1'
        try:
            quantity = max(1, int(qty_raw or 1))
        except (TypeError, ValueError):
            quantity = 1
        rtype = (return_types[i] if i < len(return_types) else ReturnRequest.ReturnType.RETURN).strip()
        if rtype not in valid_types:
            rtype = ReturnRequest.ReturnType.RETURN
        rows.append({
            'item_name': item_name,
            'item_number': (item_numbers[i] if i < len(item_numbers) else '').strip(),
            'unit': (units[i] if i < len(units) else '').strip(),
            'package': (packages[i] if i < len(packages) else '').strip(),
            'quantity': quantity,
            'return_type': rtype,
            'reason': reason,
        })

    if not rows:
        messages.error(request, 'أضف صنفاً واحداً على الأقل مع الاسم وسبب الإرجاع.')
        return redirect('ops:returns')

    batch = ReturnBatch.objects.create(
        representative=representative,
        branch=branch,
        created_by=request.user,
    )
    for row in rows:
        ReturnRequest.objects.create(
            batch=batch,
            representative=representative,
            created_by=request.user,
            return_number=batch.return_number,
            **row,
        )

    messages.success(
        request,
        f'تم حفظ ملف المرتجع {batch.return_number} بـ {len(rows)} صنف.',
    )
    # Ensure PDF token exists before WhatsApp (for download link)
    batch.ensure_public_token()
    if not batch.public_token:
        batch.save(update_fields=['public_token'])
    # Never block the HTTP worker on Evolution — hanging sendMedia kills Gunicorn (500)
    schedule_return_notify(batch.pk, request.user.pk)
    messages.info(request, 'جاري إرسال PDF للمندوب (للتعميد) وللعمليات والمحاسب (للمتابعة).')
    return _redirect_returns(batch.pk)


def _pdf_http_response(pdf_bytes: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    # ASCII-safe filename for Content-Disposition (WhatsApp / mobile browsers)
    import re

    safe = (filename or 'return.pdf').replace('"', '').replace('#', '')
    safe = re.sub(r'[^\w.\-]+', '_', safe).strip('._') or 'return'
    if not safe.lower().endswith('.pdf'):
        safe = f'{safe}.pdf'
    # inline helps in-app browsers open/download instead of opaque attachment fail
    response['Content-Disposition'] = f'inline; filename="{safe}"'
    response['Content-Length'] = str(len(pdf_bytes))
    response['Content-Type'] = 'application/pdf'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=300'
    return response


@login_required
def return_batch_pdf(request, pk):
    """Download return batch as PDF (logged-in users with access)."""
    batch = get_object_or_404(
        _return_batch_queryset(request.user).prefetch_related('items'),
        pk=pk,
    )
    try:
        pdf_bytes, filename = build_return_batch_pdf(batch)
    except Exception:
        messages.error(request, 'تعذّر إنشاء ملف PDF.')
        return redirect('ops:returns')
    return _pdf_http_response(pdf_bytes, filename)


@require_http_methods(['GET'])
def return_batch_pdf_public(request, token):
    """Public PDF download via token (shared on WhatsApp)."""
    batch = get_object_or_404(
        ReturnBatch.objects.select_related(
            'representative', 'created_by'
        ).prefetch_related('items'),
        public_token=token,
    )
    pdf_bytes, filename = build_return_batch_pdf(batch)
    return _pdf_http_response(pdf_bytes, filename)


@login_required
@require_POST
def return_batch_delete(request, pk):
    batch = get_object_or_404(_return_batch_queryset(request.user), pk=pk)
    can_delete = request.user.is_manager or (
        batch.representative_id == request.user.id
        or batch.created_by_id == request.user.id
    )
    if not can_delete:
        messages.error(request, 'لا يمكنك حذف هذا المرتجع.')
        return redirect('ops:returns')
    label = batch.return_number
    batch.delete()
    messages.success(request, f'تم حذف المرتجع {label} وجميع أصنافه.')
    return redirect('ops:returns')


@login_required
@require_POST
def return_item_update(request, pk):
    item = _return_item_or_404(pk)
    batch = item.batch
    can_edit = request.user.is_manager or (
        batch and batch.representative_id == request.user.id
    ) or item.representative_id == request.user.id
    if not can_edit:
        messages.error(request, 'لا يمكنك تعديل هذا الصنف.')
        return redirect('ops:returns')
    if item.status != ReturnRequest.Status.PENDING:
        messages.error(request, 'لا يمكن تعديل صنف تمت معالجته.')
        return _redirect_returns(batch.pk if batch else None)

    item_name = (request.POST.get('item_name') or '').strip()
    reason = (request.POST.get('reason') or '').strip()
    if not item_name or not reason:
        messages.error(request, 'الاسم وسبب الإرجاع مطلوبان.')
        return _redirect_returns(batch.pk if batch else None)

    try:
        quantity = max(1, int(request.POST.get('quantity') or 1))
    except (TypeError, ValueError):
        quantity = 1
    rtype = (request.POST.get('return_type') or '').strip()
    if rtype not in dict(ReturnRequest.ReturnType.choices):
        rtype = item.return_type

    item.item_name = item_name
    item.item_number = (request.POST.get('item_number') or '').strip()
    item.unit = (request.POST.get('unit') or '').strip()
    item.package = (request.POST.get('package') or '').strip()
    item.quantity = quantity
    item.return_type = rtype
    item.reason = reason
    item.save()
    messages.success(request, 'تم حفظ تعديلات الصنف.')
    return _redirect_returns(batch.pk if batch else None)


@login_required
@require_POST
def return_rep_authorize(request, pk):
    ret = _return_item_or_404(pk)
    can_decide = request.user.is_manager or ret.representative_id == request.user.id
    if not can_decide:
        messages.error(request, 'لا يمكنك تعميد هذا الصنف.')
        return redirect('ops:returns')
    if ret.rep_decision != ReturnRequest.RepDecision.PENDING:
        messages.error(request, 'تم اتخاذ قرار المندوب مسبقاً.')
        return _redirect_returns(ret.batch_id)
    if ret.status != ReturnRequest.Status.PENDING:
        messages.error(request, 'لا يمكن التعميد بعد معالجة الصنف.')
        return _redirect_returns(ret.batch_id)

    ret.rep_decision = ReturnRequest.RepDecision.AUTHORIZED
    ret.rep_decided_by = request.user
    ret.rep_decided_at = timezone.now()
    ret.save(update_fields=['rep_decision', 'rep_decided_by', 'rep_decided_at', 'updated_at'])
    messages.success(request, f'تم تعميد الصنف «{ret.item_name}».')
    schedule_return_authorized(ret.pk, request.user.pk)
    messages.info(request, 'جاري إشعار المحاسب والمستلم والعمليات عبر واتساب.')
    return _redirect_returns(ret.batch_id)


@login_required
@require_POST
def return_rep_reject(request, pk):
    ret = _return_item_or_404(pk)
    can_decide = request.user.is_manager or ret.representative_id == request.user.id
    if not can_decide:
        messages.error(request, 'لا يمكنك رفض هذا الصنف.')
        return redirect('ops:returns')
    if ret.rep_decision != ReturnRequest.RepDecision.PENDING:
        messages.error(request, 'تم اتخاذ قرار المندوب مسبقاً.')
        return _redirect_returns(ret.batch_id)
    if ret.status != ReturnRequest.Status.PENDING:
        messages.error(request, 'لا يمكن الرفض بعد معالجة الصنف.')
        return _redirect_returns(ret.batch_id)

    ret.rep_decision = ReturnRequest.RepDecision.REJECTED
    ret.rep_decided_by = request.user
    ret.rep_decided_at = timezone.now()
    ret.status = ReturnRequest.Status.REJECTED
    ret.reviewed_by = request.user
    ret.save(update_fields=[
        'rep_decision', 'rep_decided_by', 'rep_decided_at',
        'status', 'reviewed_by', 'updated_at',
    ])
    messages.success(request, f'تم رفض الصنف «{ret.item_name}» من المندوب.')
    notify_roles(
        'رفض مرتجع (مندوب)',
        f'{ret.return_number or (ret.batch.return_number if ret.batch_id else "")} — {ret.item_name}\n'
        f'بواسطة: {request.user.display_name}',
    )
    return _redirect_returns(ret.batch_id)


@manager_required
@require_POST
def return_accept(request, pk):
    ret = get_object_or_404(ReturnRequest, pk=pk, status=ReturnRequest.Status.PENDING)
    if ret.rep_decision != ReturnRequest.RepDecision.AUTHORIZED:
        messages.error(request, 'يجب تعميد المندوب أولاً قبل قبول الصنف.')
        return _redirect_returns(ret.batch_id)
    ret.status = ReturnRequest.Status.ACCEPTED
    ret.reviewed_by = request.user
    ret.save(update_fields=['status', 'reviewed_by', 'updated_at'])
    messages.success(request, f'تم قبول الصنف «{ret.item_name}».')
    notify_roles(
        'قبول مرتجع',
        f'{ret.return_number or (ret.batch.return_number if ret.batch_id else "")} — {ret.item_name}\n'
        f'بواسطة: {request.user.display_name}',
    )
    return _redirect_returns(ret.batch_id)


@manager_required
@require_POST
def return_reject(request, pk):
    ret = get_object_or_404(ReturnRequest, pk=pk, status=ReturnRequest.Status.PENDING)
    ret.status = ReturnRequest.Status.REJECTED
    ret.reviewed_by = request.user
    ret.save(update_fields=['status', 'reviewed_by', 'updated_at'])
    messages.success(request, f'تم رفض الصنف «{ret.item_name}».')
    notify_roles(
        'رفض مرتجع',
        f'{ret.return_number or (ret.batch.return_number if ret.batch_id else "")} — {ret.item_name}\n'
        f'بواسطة: {request.user.display_name}',
    )
    return _redirect_returns(ret.batch_id)


def _daily_order_queryset(user):
    qs = DailyOrder.objects.select_related('representative', 'created_by')
    if user.is_representative:
        qs = qs.filter(representative=user)
    return qs


@login_required
def daily_orders_list(request):
    qs = _daily_order_queryset(request.user)
    q = (request.GET.get('q') or '').strip()
    date_raw = (request.GET.get('date') or '').strip()
    today = timezone.localdate()
    if date_raw:
        try:
            order_date = datetime.strptime(date_raw, '%Y-%m-%d').date()
        except ValueError:
            order_date = today
    else:
        order_date = today
    qs = qs.filter(order_date=order_date)
    if q:
        qs = qs.filter(
            Q(order_number__icontains=q)
            | Q(batch_number__icontains=q)
            | Q(item_name__icontains=q)
            | Q(item_number__icontains=q)
            | Q(branch__icontains=q)
            | Q(supplier__icontains=q)
            | Q(representative__first_name__icontains=q)
            | Q(representative__last_name__icontains=q)
            | Q(representative__username__icontains=q)
        )

    # تجميع: صف واحد لكل ملف طلبية
    batches_map = {}
    for order in qs.select_related('representative').order_by('-created_at', 'pk'):
        key = order.batch_number or f'single-{order.pk}'
        if key not in batches_map:
            batches_map[key] = {
                'key': key,
                'batch_number': order.batch_number or order.order_number,
                'seed_pk': order.pk,
                'order_date': order.order_date,
                'branch': order.branch,
                'supplier': order.supplier,
                'representative': order.representative,
                'created_at': order.created_at,
                'items': [],
                'statuses': set(),
            }
        batches_map[key]['items'].append(order)
        batches_map[key]['statuses'].add(order.status)

    batches = []
    for b in batches_map.values():
        statuses = b['statuses']
        if statuses == {DailyOrder.Status.PENDING}:
            b['display_status'] = 'pending'
        elif statuses == {DailyOrder.Status.APPROVED}:
            b['display_status'] = 'approved'
        elif statuses == {DailyOrder.Status.REJECTED}:
            b['display_status'] = 'rejected'
        else:
            b['display_status'] = 'mixed'
        b['items_count'] = len(b['items'])
        batches.append(b)
    batches.sort(key=lambda x: x['created_at'], reverse=True)

    open_batch = (request.GET.get('open') or '').strip()

    reps = User.objects.filter(role=User.Role.REPRESENTATIVE, is_active=True)
    if not reps.exists():
        representatives = User.objects.filter(is_active=True).order_by('first_name', 'username')
    else:
        representatives = reps.order_by('first_name', 'username')

    catalog = list(
        CatalogItem.objects.order_by('name').values('item_number', 'name')[:500]
    )
    return render(request, 'ops/daily_orders.html', {
        'batches': batches,
        'q': q,
        'order_date': order_date,
        'today': today,
        'open_batch': open_batch,
        'representatives': representatives,
        'branches': Branch.active_names(),
        'suppliers': Supplier.active_names(),
        'catalog': catalog,
        'catalog_json': json.dumps(catalog, ensure_ascii=False),
        'active_nav': 'orders',
    })


@login_required
@require_POST
def daily_order_create(request):
    if request.user.is_representative:
        representative = request.user
    else:
        rep_id = request.POST.get('representative')
        representative = User.objects.filter(pk=rep_id, is_active=True).first()
        if not representative:
            messages.error(request, 'اختر المندوب أولاً.')
            return redirect('ops:daily_orders')

    branch = (request.POST.get('branch') or '').strip()
    if not branch:
        messages.error(request, 'اختر الفرع.')
        return redirect('ops:daily_orders')

    supplier = (request.POST.get('supplier') or '').strip()
    if not supplier:
        messages.error(request, 'اختر المورد.')
        return redirect('ops:daily_orders')

    date_raw = (request.POST.get('order_date') or '').strip()
    today = timezone.localdate()
    if date_raw:
        try:
            order_date = datetime.strptime(date_raw, '%Y-%m-%d').date()
        except ValueError:
            order_date = today
    else:
        order_date = today

    item_names = request.POST.getlist('item_name')
    item_numbers = request.POST.getlist('item_number')
    quantities = request.POST.getlist('quantity')
    prices = request.POST.getlist('unit_price')

    import secrets
    last_batch = (
        DailyOrder.objects.exclude(batch_number='')
        .order_by('-id')
        .values_list('batch_number', flat=True)
        .first()
    )
    batch_seq = 1
    if last_batch and last_batch.startswith('#DAYB-'):
        try:
            batch_seq = int(last_batch.replace('#DAYB-', '')) + 1
        except ValueError:
            batch_seq = (DailyOrder.objects.aggregate(Max('id'))['id__max'] or 0) + 1
    else:
        batch_seq = (DailyOrder.objects.aggregate(Max('id'))['id__max'] or 0) + 1
    batch_number = f'#DAYB-{batch_seq:04d}'
    public_token = secrets.token_urlsafe(24)

    created = 0
    for i, item_name in enumerate(item_names):
        item_name = (item_name or '').strip()
        if not item_name:
            continue
        qty_raw = quantities[i] if i < len(quantities) else '1'
        try:
            quantity = max(1, int(qty_raw or 1))
        except (TypeError, ValueError):
            quantity = 1
        price_raw = prices[i] if i < len(prices) else '0'
        try:
            unit_price = Decimal(str(price_raw or '0').strip() or '0')
        except (InvalidOperation, TypeError, ValueError):
            messages.error(request, f'سعر غير صالح للصنف «{item_name}».')
            return redirect('ops:daily_orders')
        if unit_price < 0:
            messages.error(request, f'السعر يجب ألا يكون سالباً للصنف «{item_name}».')
            return redirect('ops:daily_orders')
        DailyOrder.objects.create(
            order_date=order_date,
            batch_number=batch_number,
            public_token=public_token,
            item_name=item_name,
            item_number=(item_numbers[i] if i < len(item_numbers) else '').strip(),
            quantity=quantity,
            unit_price=unit_price,
            representative=representative,
            branch=branch,
            supplier=supplier,
            created_by=request.user,
        )
        created += 1

    if not created:
        messages.error(request, 'أضف صنفاً واحداً على الأقل مع الاسم والسعر.')
        return redirect('ops:daily_orders')

    messages.success(request, f'تم تسجيل ملف طلبية {batch_number} بـ {created} صنف.')
    first = DailyOrder.objects.filter(batch_number=batch_number).order_by('pk').first()
    open_q = f'&open={first.pk}' if first else ''
    return redirect(f"{reverse('ops:daily_orders')}?date={order_date.isoformat()}{open_q}")


@manager_required
@require_POST
def daily_order_delete(request, pk):
    seed = get_object_or_404(DailyOrder, pk=pk)
    order_date = seed.order_date
    if seed.batch_number:
        label = seed.batch_number
        count, _ = DailyOrder.objects.filter(batch_number=seed.batch_number).delete()
    else:
        label = seed.order_number
        seed.delete()
        count = 1
    messages.success(request, f'تم حذف ملف الطلبية {label} ({count} صنف).')
    return redirect(f"{reverse('ops:daily_orders')}?date={order_date.isoformat()}")


@manager_required
@require_POST
def daily_order_approve(request, pk):
    seed = get_object_or_404(DailyOrder, pk=pk, status=DailyOrder.Status.PENDING)
    qs = DailyOrder.objects.filter(status=DailyOrder.Status.PENDING)
    if seed.batch_number:
        qs = qs.filter(batch_number=seed.batch_number)
    else:
        qs = qs.filter(pk=seed.pk)

    now = timezone.now()
    count = qs.update(
        status=DailyOrder.Status.APPROVED,
        reviewed_by=request.user,
        reviewed_at=now,
        updated_at=now,
    )
    seed.refresh_from_db()
    ref = seed.batch_number or seed.order_number
    messages.success(request, f'تم اعتماد ملف الطلبية {ref} ({count} صنف).')
    schedule_daily_order_approved(seed.pk, request.user.pk)
    supplier = Supplier.objects.filter(name=seed.supplier).first()
    if supplier and supplier.normalized_phone():
        messages.info(request, 'جاري إرسال ملف PDF للمورد عبر واتساب في الخلفية.')
    else:
        messages.warning(request, 'لا يوجد رقم جوال للمورد — لم يُرسل واتساب.')
    return redirect(f"{reverse('ops:daily_orders')}?date={seed.order_date.isoformat()}")


@manager_required
@require_POST
def daily_order_reject(request, pk):
    seed = get_object_or_404(DailyOrder, pk=pk, status=DailyOrder.Status.PENDING)
    qs = DailyOrder.objects.filter(status=DailyOrder.Status.PENDING)
    if seed.batch_number:
        qs = qs.filter(batch_number=seed.batch_number)
    else:
        qs = qs.filter(pk=seed.pk)
    now = timezone.now()
    count = qs.update(
        status=DailyOrder.Status.REJECTED,
        reviewed_by=request.user,
        reviewed_at=now,
        updated_at=now,
    )
    ref = seed.batch_number or seed.order_number
    messages.success(request, f'تم رفض ملف الطلبية {ref} ({count} صنف).')
    return redirect(f"{reverse('ops:daily_orders')}?date={seed.order_date.isoformat()}")


@login_required
def daily_order_batch_pdf(request, pk):
    seed = get_object_or_404(_daily_order_queryset(request.user), pk=pk)
    if seed.batch_number:
        orders = list(
            _daily_order_queryset(request.user)
            .filter(batch_number=seed.batch_number)
            .order_by('pk')
        )
    else:
        orders = [seed]
    try:
        pdf_bytes, filename = build_daily_orders_pdf(orders, actor=request.user)
    except Exception:
        messages.error(request, 'تعذّر إنشاء ملف PDF.')
        return redirect('ops:daily_orders')
    return _pdf_http_response(pdf_bytes, filename)


def daily_order_pdf_public(request, token):
    """Public PDF download via token (shared on WhatsApp)."""
    seed = DailyOrder.objects.filter(public_token=token).order_by('pk').first()
    if not seed:
        return HttpResponse('غير موجود', status=404)
    if seed.batch_number:
        orders = list(
            DailyOrder.objects.filter(batch_number=seed.batch_number).order_by('pk')
        )
    else:
        orders = [seed]
    try:
        pdf_bytes, filename = build_daily_orders_pdf(
            orders,
            actor=seed.reviewed_by or seed.created_by,
        )
    except Exception:
        return HttpResponse('تعذّر إنشاء الملف', status=500)
    return _pdf_http_response(pdf_bytes, filename)


def _parse_order_date(raw, fallback):
    raw = (raw or '').strip()
    if not raw:
        return fallback
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return fallback


def _avg_prices_by_item(qs):
    """Map item_key -> {item_number, item_name, avg_price}."""
    rows = (
        qs.values('item_number', 'item_name')
        .annotate(avg_price=Avg('unit_price'))
        .order_by('item_name')
    )
    result = {}
    for row in rows:
        number = (row['item_number'] or '').strip()
        name = (row['item_name'] or '').strip()
        key = number if number else name
        if not key:
            continue
        result[key] = {
            'item_number': number,
            'item_name': name,
            'avg_price': row['avg_price'] or Decimal('0'),
        }
    return result


@login_required
def price_compare(request):
    today = timezone.localdate()
    curr_date = _parse_order_date(request.GET.get('date'), today)
    prev_date = _parse_order_date(request.GET.get('prev_date'), curr_date - timedelta(days=1))

    branch = (request.GET.get('branch') or '').strip()
    supplier = (request.GET.get('supplier') or '').strip()
    rep_id = (request.GET.get('representative') or '').strip()

    base = _daily_order_queryset(request.user)
    if branch:
        base = base.filter(branch=branch)
    if supplier:
        base = base.filter(supplier=supplier)
    if rep_id:
        base = base.filter(representative_id=rep_id)

    prev_map = _avg_prices_by_item(base.filter(order_date=prev_date))
    curr_map = _avg_prices_by_item(base.filter(order_date=curr_date))
    keys = sorted(set(prev_map) | set(curr_map), key=lambda k: (
        (curr_map.get(k) or prev_map.get(k) or {}).get('item_name') or k
    ))

    rows = []
    for key in keys:
        prev = prev_map.get(key)
        curr = curr_map.get(key)
        prev_price = prev['avg_price'] if prev else None
        curr_price = curr['avg_price'] if curr else None
        item_number = (curr or prev or {}).get('item_number') or ''
        item_name = (curr or prev or {}).get('item_name') or key
        diff = None
        pct = None
        direction = 'missing'
        if prev_price is not None and curr_price is not None:
            diff = curr_price - prev_price
            if prev_price != 0:
                pct = (diff / prev_price) * Decimal('100')
            if diff > 0:
                direction = 'up'
            elif diff < 0:
                direction = 'down'
            else:
                direction = 'same'
        elif curr_price is not None:
            direction = 'new'
        elif prev_price is not None:
            direction = 'gone'
        rows.append({
            'item_number': item_number,
            'item_name': item_name,
            'prev_price': prev_price,
            'curr_price': curr_price,
            'diff': diff,
            'pct': pct,
            'direction': direction,
        })

    reps = User.objects.filter(role=User.Role.REPRESENTATIVE, is_active=True)
    if not reps.exists():
        representatives = User.objects.filter(is_active=True).order_by('first_name', 'username')
    else:
        representatives = reps.order_by('first_name', 'username')

    return render(request, 'ops/price_compare.html', {
        'rows': rows,
        'curr_date': curr_date,
        'prev_date': prev_date,
        'today': today,
        'filter_branch': branch,
        'filter_supplier': supplier,
        'filter_rep': rep_id,
        'branches': Branch.active_names(),
        'suppliers': Supplier.active_names(),
        'representatives': representatives,
        'active_nav': 'price_compare',
    })


@login_required
def tasks_board(request):
    qs = _task_queryset(request.user).prefetch_related('response_photos')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(description__icontains=q) | Q(branch__icontains=q)
        )

    columns = {
        'todo': qs.filter(status=Task.Status.TODO),
        'in_progress': qs.filter(status=Task.Status.IN_PROGRESS),
        'pending_review': qs.filter(status=Task.Status.PENDING_REVIEW),
        'done': qs.filter(status=Task.Status.DONE),
    }
    form = TaskForm() if request.user.is_manager else None
    return render(request, 'ops/tasks.html', {
        'columns': columns,
        'form': form,
        'q': q,
        'active_nav': 'tasks',
    })


def _public_task_url(task, request=None) -> str:
    path = reverse('ops:task_public', kwargs={'token': task.public_token})
    base = getattr(settings, 'PUBLIC_BASE_URL', '') or ''
    if base:
        return f'{base.rstrip("/")}{path}'
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def _is_allowed_task_image(uploaded) -> bool:
    name = (getattr(uploaded, 'name', '') or '').lower()
    content = (getattr(uploaded, 'content_type', '') or '').lower()
    if content.startswith('image/'):
        return True
    return name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic'))


@manager_required
@require_POST
def task_create(request):
    form = TaskForm(request.POST)
    if form.is_valid():
        task = form.save(commit=False)
        task.created_by = request.user
        task.status = Task.Status.TODO
        task.save()
        messages.success(
            request,
            'تم إنشاء المهمة وإرسال رابط الرد للموظف عبر واتساب إن وُجد الرقم.',
        )
        schedule_task_assigned(task.pk)
        notify_roles(
            'مهمة جديدة',
            f'{task.title}\n'
            f'الفرع: {task.branch or "—"}\n'
            f'الموظف: {task.assigned_to.display_name if task.assigned_to_id else "—"}\n'
            f'بواسطة: {request.user.display_name}',
        )
    else:
        messages.error(request, 'تعذر حفظ المهمة. تحقق من العنوان والموظف والفرع.')
    return redirect('ops:tasks')


@require_http_methods(['GET', 'POST'])
def task_public(request, token):
    task = get_object_or_404(
        Task.objects.select_related('assigned_to', 'created_by', 'reviewed_by')
        .prefetch_related('response_photos'),
        public_token=token,
    )
    submitted = False
    error = None

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'submit_response':
            if task.status == Task.Status.DONE:
                error = 'المهمة مغلقة ولا يمكن تعديلها.'
            elif task.status == Task.Status.PENDING_REVIEW:
                error = 'الرد قيد المراجعة حالياً.'
            else:
                text = (request.POST.get('response_text') or '').strip()
                files = request.FILES.getlist('photos')
                if not text and not files and not task.response_photos.exists():
                    error = 'أدخل نص الرد أو أرفق صورة واحدة على الأقل.'
                else:
                    bad = [f.name for f in files if not _is_allowed_task_image(f)]
                    if bad:
                        error = 'يُسمح بصور فقط (JPG/PNG/WEBP).'
                    elif len(files) > 8:
                        error = 'حد أقصى 8 صور في المرة الواحدة.'
                    else:
                        oversized = [
                            f.name for f in files
                            if getattr(f, 'size', 0) and f.size > 8 * 1024 * 1024
                        ]
                        if oversized:
                            error = 'حجم الصورة يجب ألا يتجاوز 8MB.'
                        else:
                            if text or files:
                                # keep previous text if empty update with only photos
                                if not text and task.response_text:
                                    text = task.response_text
                            task.submit_for_review(text)
                            for f in files:
                                TaskResponsePhoto.objects.create(task=task, image=f)
                            submitted = True
                            schedule_task_submitted(task.pk)
        else:
            error = 'إجراء غير معروف.'

    return render(request, 'ops/task_public.html', {
        'task': task,
        'just_submitted': submitted,
        'error': error,
        'can_respond': task.status in (
            Task.Status.TODO,
            Task.Status.IN_PROGRESS,
        ),
    })


@manager_required
@require_POST
def task_review(request, pk):
    task = get_object_or_404(
        Task.objects.select_related('assigned_to').prefetch_related('response_photos'),
        pk=pk,
    )
    action = (request.POST.get('action') or '').strip()
    note = (request.POST.get('review_note') or '').strip()

    if task.status != Task.Status.PENDING_REVIEW and action in ('approve', 'reject'):
        messages.error(request, 'هذه المهمة ليست بانتظار المراجعة.')
        return redirect('ops:tasks')

    if action == 'approve':
        task.approve_response(request.user, note)
        schedule_task_review_result(task.pk, approved=True)
        messages.success(request, 'تم اعتماد الرد وإغلاق المهمة.')
    elif action == 'reject':
        if not note:
            messages.error(request, 'اكتب ملاحظة عند رد المهمة للموظف.')
            return redirect('ops:tasks')
        task.reject_response(request.user, note)
        schedule_task_review_result(task.pk, approved=False)
        messages.success(request, 'تم رد المهمة للموظف مع الملاحظة.')
    else:
        messages.error(request, 'إجراء غير معروف.')
    return redirect('ops:tasks')


@login_required
@require_POST
def task_move(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if request.user.is_representative and task.assigned_to_id != request.user.id:
        messages.error(request, 'لا يمكنك تعديل هذه المهمة.')
        return redirect('ops:tasks')

    new_status = request.POST.get('status')
    # Employees cannot force-close without review — managers can
    if (
        new_status == Task.Status.DONE
        and not request.user.is_manager
        and task.status != Task.Status.PENDING_REVIEW
    ):
        messages.error(request, 'إغلاق المهمة يتم عبر رابط الرد ثم اعتماد المسؤول.')
        return redirect('ops:tasks')

    if new_status in dict(Task.Status.choices):
        if new_status == Task.Status.DONE:
            if request.user.is_manager and task.status == Task.Status.PENDING_REVIEW:
                task.approve_response(request.user, 'اعتماد سريع من اللوحة')
                schedule_task_review_result(task.pk, approved=True)
            else:
                task.mark_done()
        else:
            task.status = new_status
            if new_status == Task.Status.IN_PROGRESS and task.progress == 0:
                task.progress = 45
            if new_status != Task.Status.DONE:
                task.completed_at = None
            task.save(update_fields=['status', 'progress', 'completed_at', 'updated_at'])
        messages.success(request, 'تم تحديث حالة المهمة.')
    return redirect('ops:tasks')


@login_required
def settings_view(request):
    return render(request, 'ops/settings.html', {'active_nav': 'settings'})


def _normalize_branch_name(raw: str) -> str:
    name = (raw or '').strip()
    if not name:
        return ''
    if not name.startswith('فرع'):
        name = f'فرع {name}'
    return ' '.join(name.split())


@manager_required
def branches_setup(request):
    """تهيئة الفروع — تُستخدم في اختيار موقع الفرع بالمهام والطلبيات والمرتجعات."""
    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'add':
            name = _normalize_branch_name(request.POST.get('name'))
            if not name:
                messages.error(request, 'أدخل اسم الفرع.')
            elif Branch.objects.filter(name=name).exists():
                messages.error(request, f'الفرع «{name}» موجود مسبقاً.')
            else:
                last = Branch.objects.order_by('-sort_order').values_list('sort_order', flat=True).first() or 0
                make_default = not Branch.objects.filter(is_default=True).exists()
                Branch.objects.create(
                    name=name,
                    sort_order=last + 1,
                    is_active=True,
                    is_default=make_default,
                )
                messages.success(request, f'تمت إضافة «{name}».')
        elif action == 'toggle':
            branch = get_object_or_404(Branch, pk=request.POST.get('branch_id'))
            branch.is_active = not branch.is_active
            update_fields = ['is_active', 'updated_at']
            if not branch.is_active and branch.is_default:
                branch.is_default = False
                update_fields.append('is_default')
            branch.save(update_fields=update_fields)
            state = 'تفعيل' if branch.is_active else 'إيقاف'
            messages.success(request, f'تم {state} «{branch.name}».')
        elif action == 'delete':
            branch = get_object_or_404(Branch, pk=request.POST.get('branch_id'))
            label = branch.name
            branch.delete()
            messages.success(request, f'تم حذف «{label}».')
        elif action == 'rename':
            branch = get_object_or_404(Branch, pk=request.POST.get('branch_id'))
            name = _normalize_branch_name(request.POST.get('name'))
            if not name:
                messages.error(request, 'أدخل اسم الفرع.')
            elif Branch.objects.exclude(pk=branch.pk).filter(name=name).exists():
                messages.error(request, f'الاسم «{name}» مستخدم لفرع آخر.')
            else:
                branch.name = name
                branch.save(update_fields=['name', 'updated_at'])
                messages.success(request, 'تم تحديث اسم الفرع.')
        elif action == 'set_default':
            branch = get_object_or_404(Branch, pk=request.POST.get('branch_id'))
            branch.set_as_default()
            messages.success(request, f'تم تعيين «{branch.name}» كفرع افتراضي في النماذج.')
        return redirect('ops:branches')

    branches = Branch.objects.all().order_by('sort_order', 'name')
    return render(request, 'ops/branches.html', {
        'active_nav': 'branches',
        'branches': branches,
    })


def _normalize_supplier_name(raw: str) -> str:
    return ' '.join((raw or '').strip().split())


@manager_required
def suppliers_setup(request):
    """تهيئة الموردين — تُستخدم في طلبات الشراء اليومية."""
    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'add':
            name = _normalize_supplier_name(request.POST.get('name'))
            phone = normalize_whatsapp(request.POST.get('phone') or '')
            if not name:
                messages.error(request, 'أدخل اسم المورد.')
            elif Supplier.objects.filter(name=name).exists():
                messages.error(request, f'المورد «{name}» موجود مسبقاً.')
            else:
                last = Supplier.objects.order_by('-sort_order').values_list('sort_order', flat=True).first() or 0
                Supplier.objects.create(
                    name=name,
                    phone=phone,
                    sort_order=last + 1,
                    is_active=True,
                )
                messages.success(request, f'تمت إضافة «{name}».')
        elif action == 'toggle':
            supplier = get_object_or_404(Supplier, pk=request.POST.get('supplier_id'))
            supplier.is_active = not supplier.is_active
            supplier.save(update_fields=['is_active', 'updated_at'])
            state = 'تفعيل' if supplier.is_active else 'إيقاف'
            messages.success(request, f'تم {state} «{supplier.name}».')
        elif action == 'delete':
            supplier = get_object_or_404(Supplier, pk=request.POST.get('supplier_id'))
            label = supplier.name
            supplier.delete()
            messages.success(request, f'تم حذف «{label}».')
        elif action == 'rename':
            supplier = get_object_or_404(Supplier, pk=request.POST.get('supplier_id'))
            name = _normalize_supplier_name(request.POST.get('name'))
            phone = normalize_whatsapp(request.POST.get('phone') or '')
            if not name:
                messages.error(request, 'أدخل اسم المورد.')
            elif Supplier.objects.exclude(pk=supplier.pk).filter(name=name).exists():
                messages.error(request, f'الاسم «{name}» مستخدم لمورد آخر.')
            else:
                supplier.name = name
                supplier.phone = phone
                supplier.save(update_fields=['name', 'phone', 'updated_at'])
                messages.success(request, 'تم تحديث بيانات المورد.')
        return redirect('ops:suppliers')

    suppliers = Supplier.objects.all().order_by('sort_order', 'name')
    return render(request, 'ops/suppliers.html', {
        'active_nav': 'suppliers',
        'suppliers': suppliers,
    })


@manager_required
def whatsapp_hub(request):
    """شاشة ربط واتساب (QR) + أرقام الأدوار."""
    from ops.models import EvolutionConfig, WhatsAppRoleContact as RoleContact
    from ops.whatsapp import get_evolution_settings

    if request.method == 'POST' and request.POST.get('action') == 'save_evolution':
        cfg = EvolutionConfig.get_solo()
        cfg.server_url = (request.POST.get('server_url') or '').strip().rstrip('/')
        api_key = (request.POST.get('api_key') or '').strip()
        # Keep existing key if form sent masked/empty intentionally with keep flag
        if api_key:
            if len(api_key) >= 2 and api_key[0] == api_key[-1] and api_key[0] in ('"', "'"):
                api_key = api_key[1:-1].strip()
            cfg.api_key = api_key
        cfg.instance_name = (request.POST.get('instance_name') or 'farshops').strip() or 'farshops'
        cfg.notify_enabled = request.POST.get('notify_enabled') == 'on'
        cfg.verify_ssl = request.POST.get('verify_ssl') == 'on'
        if not cfg.api_key:
            messages.error(request, 'أدخل مفتاح API.')
        elif not cfg.server_url:
            messages.error(request, 'أدخل رابط خادم Evolution.')
        else:
            cfg.save()
            messages.success(request, 'تم حفظ إعدادات واتساب — يظهر زر الربط الآن.')
        return redirect('ops:whatsapp')

    if request.method == 'POST' and request.POST.get('action') == 'save_roles':
        for role_value, _label in RoleContact.ROLE_CHOICES:
            raw = (request.POST.get(f'phone_{role_value}') or '').strip()
            phone = normalize_whatsapp(raw)
            contact, _ = RoleContact.objects.get_or_create(role=role_value)
            contact.phone = phone
            contact.save(update_fields=['phone', 'updated_at'])
        messages.success(request, 'تم حفظ أرقام واتساب للأدوار.')
        return redirect('ops:whatsapp')

    contacts = {
        c.role: c.phone
        for c in WhatsAppRoleContact.objects.all()
    }
    notify_rows = []
    other_rows = []
    for value, label in WhatsAppRoleContact.ROLE_CHOICES:
        users = User.objects.filter(role=value, is_active=True).order_by('first_name', 'username')
        phone = contacts.get(value, '')
        row = {
            'value': value,
            'label': label,
            'phone': phone,
            'notify': value in User.NOTIFY_ROLES,
            'filled': bool(phone),
            'users': users,
        }
        if row['notify']:
            notify_rows.append(row)
        else:
            other_rows.append(row)

    evo = get_evolution_settings()
    db_cfg = EvolutionConfig.get_solo()
    state = connection_state()
    notify_phones = collect_notify_phones()
    notify_roles_filled = sum(1 for r in notify_rows if r['filled'])
    return render(request, 'ops/whatsapp.html', {
        'active_nav': 'whatsapp',
        'notify_rows': notify_rows,
        'other_rows': other_rows,
        'wa_state': state,
        'instance_name': evo['instance_name'],
        'server_url': evo['server_url'],
        'has_api_key': bool(evo['api_key']),
        'api_key_source': evo['source'],
        'api_key_env_set': any(k.upper() == 'EVOLUTION_API_KEY' for k in os.environ),
        'api_key_len': len(evo['api_key'] or ''),
        'evo_form': {
            'server_url': db_cfg.server_url or evo['server_url'],
            'api_key': db_cfg.api_key or '',
            'instance_name': db_cfg.instance_name or evo['instance_name'],
            'notify_enabled': db_cfg.notify_enabled if db_cfg.api_key else True,
            'verify_ssl': db_cfg.verify_ssl,
        },
        'notify_enabled': evo['notify_enabled'],
        'notify_phones_count': len(notify_phones),
        'notify_phones': notify_phones,
        'notify_roles_filled': notify_roles_filled,
        'notify_roles_total': len(notify_rows),
    })


@manager_required
def whatsapp_qr_api(request):
    force = request.GET.get('force') in ('1', 'true', 'yes') or request.method == 'POST'
    data = fetch_qr(force=force)
    return JsonResponse(data)


@manager_required
def whatsapp_status_api(request):
    return JsonResponse(connection_state())


@manager_required
@require_POST
def whatsapp_logout_api(request):
    return JsonResponse(logout_instance())


@manager_required
@require_POST
def whatsapp_recreate_api(request):
    return JsonResponse(recreate_instance())


@manager_required
@require_POST
def whatsapp_test_api(request):
    return JsonResponse(send_test_to_roles())


@login_required
def items_list(request):
    qs = CatalogItem.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(item_number__icontains=q)
            | Q(unit__icontains=q)
            | Q(package__icontains=q)
        )
    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'ops/items.html', {
        'items': page,
        'page_obj': page,
        'q': q,
        'total_items': CatalogItem.objects.count(),
        'active_nav': 'items',
    })


@login_required
@require_POST
def item_create(request):
    name = (request.POST.get('name') or '').strip()
    item_number = (request.POST.get('item_number') or '').strip()
    unit = (request.POST.get('unit') or '').strip()
    package = (request.POST.get('package') or '').strip()

    if not name or not item_number:
        messages.error(request, 'الاسم ورقم الصنف مطلوبان.')
        return redirect('ops:items')

    if CatalogItem.objects.filter(item_number=item_number).exists():
        messages.error(request, f'رقم الصنف «{item_number}» موجود مسبقاً.')
        return redirect('ops:items')

    CatalogItem.objects.create(
        name=name,
        item_number=item_number,
        unit=unit,
        package=package,
    )
    messages.success(request, f'تم إضافة الصنف «{name}».')
    return redirect('ops:items')


@login_required
@require_POST
def item_delete(request, pk):
    item = get_object_or_404(CatalogItem, pk=pk)
    label = item.name
    item.delete()
    messages.success(request, f'تم حذف الصنف «{label}».')
    return redirect('ops:items')


@login_required
@require_POST
def items_import_excel(request):
    from .excel_items import parse_items_workbook

    upload = request.FILES.get('excel_file')
    if not upload:
        messages.error(request, 'اختر ملف Excel أولاً.')
        return redirect('ops:items')

    name_lower = upload.name.lower()
    if not (name_lower.endswith('.xlsx') or name_lower.endswith('.xlsm')):
        messages.error(request, 'الصيغة المدعومة: .xlsx فقط.')
        return redirect('ops:items')

    try:
        rows, parse_errors = parse_items_workbook(upload)
    except Exception:
        messages.error(request, 'تعذر قراءة الملف. تأكد أنه Excel صالح.')
        return redirect('ops:items')

    created = 0
    updated = 0
    for row in rows:
        obj, was_created = CatalogItem.objects.update_or_create(
            item_number=row['item_number'],
            defaults={
                'name': row['name'],
                'unit': row['unit'],
                'package': row['package'],
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1

    if created or updated:
        messages.success(
            request,
            f'تم الاستيراد: {created} جديد، {updated} محدّث.'
            + (f' ({len(parse_errors)} صفوف بها مشاكل)' if parse_errors else ''),
        )
    elif parse_errors:
        messages.error(request, 'لم يُستورد شيء. ' + ' '.join(parse_errors[:3]))
    else:
        messages.error(request, 'لا توجد بيانات صالحة في الملف.')

    if parse_errors and (created or updated):
        for err in parse_errors[:5]:
            messages.warning(request, err)

    return redirect('ops:items')


@login_required
def items_template_download(request):
    from django.http import HttpResponse

    from .excel_items import build_template_workbook

    stream = build_template_workbook()
    response = HttpResponse(
        stream.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="items_template.xlsx"'
    return response
