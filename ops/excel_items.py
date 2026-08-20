"""استيراد أصناف من ملفات Excel."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook, load_workbook

HEADER_ALIASES = {
    'name': {'الاسم', 'اسم', 'name', 'item_name', 'الصنف'},
    'item_number': {'رقم الصنف', 'رقم', 'item_number', 'رقمالصنف', 'كود', 'code', 'sku'},
    'unit': {'الوحدة', 'وحدة', 'unit'},
    'package': {'العبوة', 'عبوة', 'package', 'pack'},
}


def _norm(value) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _map_headers(row) -> dict[str, int]:
    mapping = {}
    for idx, cell in enumerate(row):
        key = _norm(cell).lower().replace(' ', '')
        for field, aliases in HEADER_ALIASES.items():
            normalized_aliases = {a.lower().replace(' ', '') for a in aliases}
            if key in normalized_aliases and field not in mapping:
                mapping[field] = idx
                break
    return mapping


def parse_items_workbook(file_obj) -> tuple[list[dict], list[str]]:
    """
    يقرأ ملف Excel ويعيد (صفوف صالحة, أخطاء).
    الصف المتوقع: الاسم | رقم الصنف | الوحدة | العبوة
    """
    wb = load_workbook(file_obj, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return [], ['الملف فارغ.']

    header_map = _map_headers(rows[0])
    # إن لم تُعرف العناوين، نفترض الترتيب الثابت
    if 'name' not in header_map or 'item_number' not in header_map:
        header_map = {'name': 0, 'item_number': 1, 'unit': 2, 'package': 3}
        data_rows = rows
        # تخطّي الصف الأول إن بدا كعناوين عربية/إنجليزية
        first = [_norm(c).lower() for c in (rows[0] or ())]
        if any(h in first for h in ('الاسم', 'name', 'رقم الصنف', 'item_number')):
            data_rows = rows[1:]
    else:
        data_rows = rows[1:]

    items = []
    errors = []
    seen_numbers = set()

    for i, row in enumerate(data_rows, start=2):
        if not row or all(c is None or str(c).strip() == '' for c in row):
            continue

        def cell(field, default=''):
            idx = header_map.get(field)
            if idx is None or idx >= len(row):
                return default
            return _norm(row[idx])

        name = cell('name')
        item_number = cell('item_number')
        unit = cell('unit')
        package = cell('package')

        if not name and not item_number:
            continue
        if not name:
            errors.append(f'الصف {i}: الاسم مطلوب.')
            continue
        if not item_number:
            errors.append(f'الصف {i}: رقم الصنف مطلوب.')
            continue
        if item_number in seen_numbers:
            errors.append(f'الصف {i}: رقم الصنف مكرر في الملف ({item_number}).')
            continue
        seen_numbers.add(item_number)
        items.append({
            'name': name,
            'item_number': item_number,
            'unit': unit,
            'package': package,
        })

    return items, errors


def build_template_workbook() -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = 'الأصناف'
    ws.append(['الاسم', 'رقم الصنف', 'الوحدة', 'العبوة'])
    ws.append(['كرسي مكتب', 'CHR-001', 'قطعة', 'كرتون'])
    ws.append(['طاولة اجتماعات', 'DSK-100', 'قطعة', 'طبلية'])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 22
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream
