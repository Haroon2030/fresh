"""دمج وحدات/عبوات الأصناف في حقل واحد."""

from __future__ import annotations

UNIT_SEP = '، '


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
            merged[key] = {
                'name': name,
                'item_number': (row.get('item_number') or '').strip(),
                'units': [],
            }
            order.append(key)

        entry = merged[key]
        item_number = (row.get('item_number') or '').strip()
        if item_number and not entry['item_number']:
            entry['item_number'] = item_number

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
