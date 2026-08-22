"""دمج وحدات/عبوات الأصناف في حقل واحد."""

from __future__ import annotations

from .daily_order_packages import DAILY_ORDER_PACKAGES

UNIT_SEP = '، '
PACKAGE_NAMES = frozenset(DAILY_ORDER_PACKAGES)


def split_units(value: str) -> list[str]:
    if not value:
        return []
    parts = []
    for chunk in str(value).replace('،', ',').split(','):
        unit = chunk.strip()
        if unit and unit not in parts:
            parts.append(unit)
    return parts


def join_units(units: list[str]) -> str:
    cleaned = split_units(UNIT_SEP.join(units))
    return UNIT_SEP.join(cleaned)


def merge_unit_strings(*values: str) -> str:
    parts: list[str] = []
    for value in values:
        for unit in split_units(value):
            if unit not in parts:
                parts.append(unit)
    return join_units(parts)


def looks_like_item_number(value: str) -> bool:
    value = (value or '').strip()
    if not value:
        return False
    digits = value.replace('.', '').replace('-', '')
    return digits.isdigit() and len(digits) >= 3


def split_item_number(value: str) -> tuple[str, list[str]]:
    """يفصل رقم الصنf عن قيم عبوة/وحدة إن وُجدت في نفس الخانة."""
    value = (value or '').strip()
    if not value:
        return '', []
    if '،' not in value and ',' not in value:
        return value, []

    parts = split_units(value)
    sku = ''
    extras: list[str] = []
    for part in parts:
        if looks_like_item_number(part):
            if not sku:
                sku = part
            else:
                extras.append(part)
        else:
            extras.append(part)
    if not sku and parts:
        sku = parts[0]
    return sku, extras


def normalize_catalog_item_fields(
    item_number: str,
    unit: str,
    package: str = '',
) -> tuple[str, str]:
    """
    يصحّح رقم الصنf والوحدات عندما يُخزَّن الرقم في unit
    أو تُخزَّن عبوة (جرm، كيس…) في item_number.
    """
    raw_number = (item_number or '').strip()
    sku = ''
    units: list[str] = []

    number_sku, number_extras = split_item_number(raw_number)
    if looks_like_item_number(number_sku):
        sku = number_sku
    elif raw_number in PACKAGE_NAMES and raw_number not in units:
        units.append(raw_number)
    for extra in number_extras:
        if looks_like_item_number(extra):
            if not sku:
                sku = extra
        elif extra not in units:
            units.append(extra)

    for part in split_units(unit) + split_units(package):
        if looks_like_item_number(part):
            if not sku:
                sku = part
        elif part not in units:
            units.append(part)

    if not sku and looks_like_item_number(raw_number):
        sku = raw_number

    if sku in PACKAGE_NAMES:
        sku = ''

    return sku, join_units(units)


def sanitize_catalog_row(
    name: str,
    package: str,
    item_number: str,
    *,
    last_name: str = '',
) -> tuple[str, str, str, list[str]]:
    """
    يصحّح الحقول الشائعة الخاطئة من Excel:
    - اسم = عبوة (فلين) مع رقم في عمود العبوة
    - رقم الصنf يحتوي «06139، فلين»
    """
    name = (name or '').strip()
    package = (package or '').strip()
    item_number = (item_number or '').strip()
    extra_units: list[str] = []

    item_number, num_extras = split_item_number(item_number)
    extra_units.extend(num_extras)

    if looks_like_item_number(package) and not looks_like_item_number(item_number):
        item_number = package
        package = ''
    elif looks_like_item_number(package) and looks_like_item_number(item_number):
        package = ''

    if name in PACKAGE_NAMES:
        if last_name:
            extra_units.append(name)
            name = last_name
        elif looks_like_item_number(package):
            extra_units.append(name)
            item_number = item_number or package
            package = ''
        elif package in PACKAGE_NAMES:
            extra_units.append(name)
            name = package
            package = ''

    if package in PACKAGE_NAMES:
        extra_units.append(package)
        package = ''
    elif package:
        extra_units.append(package)
        package = ''

    return name, item_number, package, extra_units


def aggregate_catalog_rows(rows: list[dict]) -> list[dict]:
    """صف واحد لكل اسم — العبوات/الوحدات في حقل unit."""
    merged: dict[str, dict] = {}
    order: list[str] = []

    for row in rows:
        name = (row.get('name') or '').strip()
        if not name:
            continue
        key = name.casefold()
        if key not in merged:
            clean_number, num_extras = split_item_number((row.get('item_number') or '').strip())
            merged[key] = {
                'name': name,
                'item_number': clean_number,
                'units': list(num_extras),
            }
            order.append(key)

        entry = merged[key]
        item_number = (row.get('item_number') or '').strip()
        if item_number:
            clean_number, num_extras = split_item_number(item_number)
            if clean_number and not entry['item_number']:
                entry['item_number'] = clean_number
            for unit in num_extras:
                if unit not in entry['units']:
                    entry['units'].append(unit)

        for field in ('package', 'unit'):
            value = (row.get(field) or '').strip()
            if value and value not in entry['units']:
                entry['units'].append(value)

    return [
        {
            'name': merged[key]['name'],
            'item_number': merged[key]['item_number'],
            'unit': join_units(merged[key]['units']),
            'package': '',
        }
        for key in order
    ]
