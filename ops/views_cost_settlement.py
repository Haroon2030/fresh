"""Views: تسوية التكاليف — صفحة مطابقة للنموذج الورقي."""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .cost_settlement_template import COST_SETTLEMENT_LEFT_ITEMS, COST_SETTLEMENT_RIGHT_ITEMS
from .models import AccountingAccount, Branch, CostSettlement, CostSettlementLine
from .notify_ops import schedule_cost_settlement_notify
from .pdf_docs import build_cost_settlement_pdf
from .views import _pdf_http_response


def _dec(value, default='0'):
    try:
        raw = str(value or '').strip().replace(',', '')
        if raw == '':
            return Decimal(default)
        return Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _next_batch_number():
    last = (
        CostSettlement.objects.filter(batch_number__startswith='#CSTB-')
        .order_by('-batch_number')
        .values_list('batch_number', flat=True)
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(str(last).replace('#CSTB-', '')) + 1
        except ValueError:
            seq = (CostSettlement.objects.aggregate(m=Max('pk')).get('m') or 0) + 1
    return f'#CSTB-{seq:04d}'


def _parse_template_lines(post):
    lines = []
    for side, names in (('right', COST_SETTLEMENT_RIGHT_ITEMS), ('left', COST_SETTLEMENT_LEFT_ITEMS)):
        qty_list = post.getlist(f'qty_{side}')
        price_list = post.getlist(f'price_{side}')
        for i, name in enumerate(names):
            qty = _dec(qty_list[i] if i < len(qty_list) else '0')
            price = _dec(price_list[i] if i < len(price_list) else '0')
            lines.append({
                'item_name': name,
                'quantity': qty,
                'unit_price': price,
                'column_side': side,
                'sort_order': i,
            })
    return lines


CUSTOM_SORT_BASE = 1000


def _parse_custom_lines(post):
    names = post.getlist('custom_name')
    qtys = post.getlist('custom_qty')
    prices = post.getlist('custom_price')
    lines = []
    idx = 0
    for i, raw_name in enumerate(names):
        name = (raw_name or '').strip()
        qty = _dec(qtys[i] if i < len(qtys) else '0')
        price = _dec(prices[i] if i < len(prices) else '0')
        if not name and qty <= 0 and price <= 0:
            continue
        if not name:
            name = f'صنف إضافي {idx + 1}'
        lines.append({
            'item_name': name,
            'quantity': qty,
            'unit_price': price,
            'column_side': 'right',
            'sort_order': CUSTOM_SORT_BASE + idx,
        })
        idx += 1
    return lines


def _parse_all_lines(post):
    return _parse_template_lines(post) + _parse_custom_lines(post)


def _posted_custom_rows(post):
    names = post.getlist('custom_name')
    qtys = post.getlist('custom_qty')
    prices = post.getlist('custom_price')
    rows = []
    for i, raw_name in enumerate(names):
        qty = _dec(qtys[i] if i < len(qtys) else '0')
        price = _dec(prices[i] if i < len(prices) else '0')
        rows.append({
            'item_name': raw_name or '',
            'quantity': qtys[i] if i < len(qtys) else '',
            'unit_price': prices[i] if i < len(prices) else '',
            'line_total': qty * price,
        })
    return rows


def _posted_columns(post):
    def col(side, names):
        qty_list = post.getlist(f'qty_{side}')
        price_list = post.getlist(f'price_{side}')
        rows = []
        for i, name in enumerate(names):
            qty = _dec(qty_list[i] if i < len(qty_list) else '0')
            price = _dec(price_list[i] if i < len(price_list) else '0')
            rows.append({
                'item_name': name,
                'quantity': qty_list[i] if i < len(qty_list) else '',
                'unit_price': price_list[i] if i < len(price_list) else '',
                'line_total': qty * price,
            })
        return rows

    return {
        'right_rows': col('right', COST_SETTLEMENT_RIGHT_ITEMS),
        'left_rows': col('left', COST_SETTLEMENT_LEFT_ITEMS),
        'custom_rows': _posted_custom_rows(post),
    }


def _build_form_columns(settlement=None):
    by_key = {}
    custom_rows = []
    if settlement is not None:
        for line in settlement.lines.all():
            if line.sort_order >= CUSTOM_SORT_BASE:
                custom_rows.append({
                    'item_name': line.item_name,
                    'quantity': ('' if line.quantity == 0 else line.quantity),
                    'unit_price': ('' if line.unit_price == 0 else line.unit_price),
                    'line_total': line.line_total,
                })
            else:
                by_key[(line.column_side, line.sort_order)] = line

    def col(side, names):
        rows = []
        for i, name in enumerate(names):
            line = by_key.get((side, i))
            rows.append({
                'item_name': name,
                'quantity': ('' if not line or line.quantity == 0 else line.quantity),
                'unit_price': ('' if not line or line.unit_price == 0 else line.unit_price),
                'line_total': line.line_total if line else Decimal('0'),
            })
        return rows

    return {
        'right_rows': col('right', COST_SETTLEMENT_RIGHT_ITEMS),
        'left_rows': col('left', COST_SETTLEMENT_LEFT_ITEMS),
        'custom_rows': custom_rows,
    }


def _form_meta_from_post(post, today):
    date_raw = (post.get('settlement_date') or '').strip()
    account_id = (post.get('accounting_account') or '').strip()
    vehicle_amount = _dec(post.get('vehicle_amount'))
    try:
        settlement_date = datetime.strptime(date_raw, '%Y-%m-%d').date() if date_raw else today
    except ValueError:
        settlement_date = today
    account = None
    if account_id.isdigit():
        account = AccountingAccount.objects.filter(pk=int(account_id), is_active=True).first()
    return {
        'branch': Branch.COMPANY_NAME,
        'settlement_date': settlement_date,
        'account': account,
        'account_id': account_id,
        'entry_amount': Decimal('0'),
        'vehicle_amount': vehicle_amount,
    }


@login_required
def cost_settlement_list(request):
    qs = (
        CostSettlement.objects.select_related('accounting_account', 'created_by')
        .prefetch_related(
            Prefetch('lines', queryset=CostSettlementLine.objects.order_by('column_side', 'sort_order'))
        )
    )
    if request.user.is_representative:
        qs = qs.filter(created_by=request.user)
    status_filter = (request.GET.get('status') or '').strip()
    if status_filter in {c.value for c in CostSettlement.Status}:
        qs = qs.filter(status=status_filter)

    company_name = Branch.COMPANY_NAME
    batches = []
    for row in qs:
        filled = [ln for ln in row.lines.all() if (ln.quantity or 0) > 0]
        cols = _build_form_columns(row)
        batches.append({
            'seed_pk': row.pk,
            'batch_number': row.batch_number,
            'branch': row.branch or company_name,
            'settlement_date': row.settlement_date,
            'account': row.accounting_account,
            'status': row.status,
            'items_count': len(filled),
            'entry_amount': row.entry_amount,
            'vehicle_amount': row.vehicle_amount,
            'grand_total': row.grand_total,
            'created_by': row.created_by,
            'items': filled,
            'right_rows': cols['right_rows'],
            'left_rows': cols['left_rows'],
            'custom_rows': cols['custom_rows'],
        })

    return render(request, 'ops/cost_settlements.html', {
        'active_nav': 'cost_settlements',
        'batches': batches,
        'company_name': company_name,
        'status_filter': status_filter,
        'open': request.GET.get('open') or '',
    })


@login_required
@require_http_methods(['GET', 'POST'])
def cost_settlement_create(request):
    accounts = AccountingAccount.objects.filter(is_active=True)
    today = timezone.localdate()
    company_name = Branch.COMPANY_NAME

    if request.method == 'POST':
        meta = _form_meta_from_post(request.POST, today)
        lines_data = _parse_all_lines(request.POST)
        filled = [ln for ln in lines_data if ln['quantity'] > 0 or ln['unit_price'] > 0]
        if not filled and meta['entry_amount'] <= 0 and meta['vehicle_amount'] <= 0:
            messages.error(request, 'أدخل عدداً أو سعراً لصنف واحد على الأقل، أو قيمة السيارة.')
            return render(request, 'ops/cost_settlement_create.html', {
                'active_nav': 'cost_settlements',
                'accounts': accounts,
                'company_name': company_name,
                'settlement_date': meta['settlement_date'],
                'branch': company_name,
                'account_id': meta['account_id'],
                'entry_amount': '',
                'vehicle_amount': meta['vehicle_amount'],
                **_posted_columns(request.POST),
            })

        with transaction.atomic():
            settlement = CostSettlement.objects.create(
                batch_number=_next_batch_number(),
                branch=Branch.COMPANY_NAME,
                settlement_date=meta['settlement_date'],
                accounting_account=meta['account'],
                entry_amount=meta['entry_amount'],
                vehicle_amount=meta['vehicle_amount'],
                status=CostSettlement.Status.POSTED,
                created_by=request.user,
            )
            CostSettlementLine.objects.bulk_create([
                CostSettlementLine(settlement=settlement, **ln) for ln in lines_data
            ])

        settlement.ensure_public_token()
        if not settlement.public_token:
            settlement.save(update_fields=['public_token'])
        schedule_cost_settlement_notify(settlement.pk, request.user.pk)
        messages.success(request, f'تم حفظ الملف {settlement.batch_number}.')
        messages.info(
            request,
            'جاري إرسال PDF للمستلم والمحاسب والمدير والعمليات والمدخل.',
        )
        return redirect(f"{reverse('ops:cost_settlements')}?open={settlement.pk}")

    return render(request, 'ops/cost_settlement_create.html', {
        'active_nav': 'cost_settlements',
        'accounts': accounts,
        'company_name': company_name,
        'settlement_date': today,
        'branch': company_name,
        'account_id': '',
        'entry_amount': '',
        'vehicle_amount': '',
        **_build_form_columns(),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def cost_settlement_update(request, pk):
    settlement = get_object_or_404(
        CostSettlement.objects.select_related('accounting_account').prefetch_related('lines'),
        pk=pk,
    )
    if request.user.is_representative and settlement.created_by_id != request.user.id:
        messages.error(request, 'غير مصرح بتعديل هذا الملف.')
        return redirect('ops:cost_settlements')
    if not (request.user.is_manager or settlement.created_by_id == request.user.id):
        messages.error(request, 'غير مصرح بتعديل هذا الملف.')
        return redirect('ops:cost_settlements')

    accounts = AccountingAccount.objects.filter(is_active=True)
    today = timezone.localdate()
    company_name = Branch.COMPANY_NAME

    if request.method == 'POST':
        meta = _form_meta_from_post(request.POST, today)
        lines_data = _parse_all_lines(request.POST)
        with transaction.atomic():
            settlement.branch = Branch.COMPANY_NAME
            settlement.settlement_date = meta['settlement_date']
            settlement.accounting_account = meta['account']
            settlement.entry_amount = meta['entry_amount']
            settlement.vehicle_amount = meta['vehicle_amount']
            settlement.save()
            settlement.lines.all().delete()
            CostSettlementLine.objects.bulk_create([
                CostSettlementLine(settlement=settlement, **ln) for ln in lines_data
            ])
        settlement.ensure_public_token()
        if not settlement.public_token:
            settlement.save(update_fields=['public_token'])
        schedule_cost_settlement_notify(settlement.pk, request.user.pk)
        messages.success(request, f'تم تحديث الملف {settlement.batch_number}.')
        messages.info(
            request,
            'جاري إرسال PDF للمستلم والمحاسب والمدير والعمليات والمدخل.',
        )
        return redirect(f"{reverse('ops:cost_settlements')}?open={settlement.pk}")

    return render(request, 'ops/cost_settlement_edit.html', {
        'active_nav': 'cost_settlements',
        'settlement': settlement,
        'accounts': accounts,
        'company_name': company_name,
        'settlement_date': settlement.settlement_date,
        'branch': company_name,
        'account_id': str(settlement.accounting_account_id or ''),
        'entry_amount': settlement.entry_amount,
        'vehicle_amount': settlement.vehicle_amount,
        **_build_form_columns(settlement),
    })


@login_required
@require_POST
def cost_settlement_delete(request, pk):
    settlement = get_object_or_404(CostSettlement, pk=pk)
    if request.user.is_representative and settlement.created_by_id != request.user.id:
        messages.error(request, 'غير مصرح بحذف هذا الملف.')
        return redirect('ops:cost_settlements')
    if not (request.user.is_manager or settlement.created_by_id == request.user.id):
        messages.error(request, 'غير مصرح بحذف هذا الملف.')
        return redirect('ops:cost_settlements')
    ref = settlement.batch_number
    settlement.delete()
    messages.success(request, f'تم حذف الملف {ref}.')
    return redirect('ops:cost_settlements')


@login_required
@require_http_methods(['GET'])
def cost_settlement_pdf(request, pk):
    settlement = get_object_or_404(
        CostSettlement.objects.select_related('created_by').prefetch_related('lines'),
        pk=pk,
    )
    if request.user.is_representative and settlement.created_by_id != request.user.id:
        messages.error(request, 'غير مصرح بعرض هذا الملف.')
        return redirect('ops:cost_settlements')
    try:
        pdf_bytes, filename = build_cost_settlement_pdf(settlement, actor=request.user)
    except Exception:
        messages.error(request, 'تعذّر إنشاء ملف PDF.')
        return redirect('ops:cost_settlements')
    return _pdf_http_response(pdf_bytes, filename)


@require_http_methods(['GET'])
def cost_settlement_pdf_public(request, token):
    """رابط PDF عام للمشاركة عبر واتساب."""
    from django.http import HttpResponse

    settlement = (
        CostSettlement.objects.select_related('created_by')
        .prefetch_related('lines')
        .filter(public_token=token)
        .first()
    )
    if not settlement:
        return HttpResponse('غير موجود', status=404)
    try:
        pdf_bytes, filename = build_cost_settlement_pdf(
            settlement,
            actor=settlement.created_by,
        )
    except Exception:
        return HttpResponse('تعذّر إنشاء الملف', status=500)
    return _pdf_http_response(pdf_bytes, filename)
