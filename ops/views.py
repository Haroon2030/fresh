from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import TaskForm
from .models import CatalogItem, ReturnBatch, ReturnRequest, SupplyOrder, Task


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
        created.append(order.order_number)

    if created:
        if len(created) == 1:
            messages.success(request, f'تم إنشاء الطلب {created[0]} بنجاح.')
        else:
            messages.success(request, f'تم إنشاء {len(created)} طلبات شراء بنجاح.')
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
    return redirect('ops:supply')


@manager_required
@require_POST
def supply_reject(request, pk):
    order = get_object_or_404(SupplyOrder, pk=pk, status=SupplyOrder.Status.PENDING)
    order.status = SupplyOrder.Status.REJECTED
    order.reviewed_by = request.user
    order.save(update_fields=['status', 'reviewed_by', 'updated_at'])
    messages.success(request, f'تم رفض الطلب {order.order_number}.')
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
        messages.error(request, 'أدخل اسم الفرع.')
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
    return _redirect_returns(batch.pk)


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
    return _redirect_returns(ret.batch_id)


@manager_required
@require_POST
def return_reject(request, pk):
    ret = get_object_or_404(ReturnRequest, pk=pk, status=ReturnRequest.Status.PENDING)
    ret.status = ReturnRequest.Status.REJECTED
    ret.reviewed_by = request.user
    ret.save(update_fields=['status', 'reviewed_by', 'updated_at'])
    messages.success(request, f'تم رفض الصنف «{ret.item_name}».')
    return _redirect_returns(ret.batch_id)


@login_required
def tasks_board(request):
    qs = _task_queryset(request.user)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

    columns = {
        'todo': qs.filter(status=Task.Status.TODO),
        'in_progress': qs.filter(status=Task.Status.IN_PROGRESS),
        'done': qs.filter(status=Task.Status.DONE),
    }
    form = TaskForm() if request.user.is_manager else None
    return render(request, 'ops/tasks.html', {
        'columns': columns,
        'form': form,
        'q': q,
        'active_nav': 'tasks',
    })


@manager_required
@require_POST
def task_create(request):
    form = TaskForm(request.POST)
    if form.is_valid():
        task = form.save(commit=False)
        task.created_by = request.user
        task.save()
        messages.success(request, 'تم إنشاء المهمة بنجاح.')
    else:
        messages.error(request, 'تعذر حفظ المهمة. تحقق من البيانات.')
    return redirect('ops:tasks')


@login_required
@require_POST
def task_move(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if request.user.is_representative and task.assigned_to_id != request.user.id:
        messages.error(request, 'لا يمكنك تعديل هذه المهمة.')
        return redirect('ops:tasks')

    new_status = request.POST.get('status')
    if new_status in dict(Task.Status.choices):
        task.status = new_status
        if new_status == Task.Status.DONE:
            task.progress = 100
        elif new_status == Task.Status.IN_PROGRESS and task.progress == 0:
            task.progress = 45
        task.save(update_fields=['status', 'progress', 'updated_at'])
        messages.success(request, 'تم تحديث حالة المهمة.')
    return redirect('ops:tasks')


@login_required
def settings_view(request):
    return render(request, 'ops/settings.html', {'active_nav': 'settings'})


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
