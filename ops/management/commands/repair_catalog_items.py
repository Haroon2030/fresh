"""إصلاح أصناf كatalog التي خُزّنت بحقول مختلطة (اسم=عبوة، رقم=06139، فلين)."""

from django.core.management.base import BaseCommand

from ops.catalog_units import (
    PACKAGE_NAMES,
    merge_unit_strings,
    normalize_catalog_item_fields,
    sanitize_catalog_row,
    split_item_number,
)
from ops.models import CatalogItem


class Command(BaseCommand):
    help = 'Repair catalog items with package names in name or merged item_number values'

    def handle(self, *args, **options):
        fixed = 0
        merged = 0
        deleted = 0

        for item in list(CatalogItem.objects.order_by('pk')):
            clean_number, num_extras = split_item_number(item.item_number)
            units = merge_unit_strings(item.unit, item.package, *num_extras)
            normalized_number, normalized_units = normalize_catalog_item_fields(
                clean_number or item.item_number,
                units,
            )

            if item.name in PACKAGE_NAMES:
                sibling = None
                if clean_number:
                    sibling = (
                        CatalogItem.objects.filter(item_number=clean_number)
                        .exclude(pk=item.pk)
                        .exclude(name__in=PACKAGE_NAMES)
                        .first()
                    )
                if sibling:
                    sibling.unit = merge_unit_strings(sibling.unit, item.name, units)
                    sibling.save(update_fields=['unit', 'updated_at'])
                    item.delete()
                    merged += 1
                    self.stdout.write(f'merged orphan «{item.name}» into «{sibling.name}»')
                else:
                    item.delete()
                    deleted += 1
                    self.stdout.write(self.style.WARNING(f'deleted orphan «{item.name}» ({item.item_number})'))
                continue

            new_name, new_number, _, extras = sanitize_catalog_row(
                item.name,
                '',
                normalized_number or item.item_number,
            )
            new_units = merge_unit_strings(normalized_units, *extras)
            changed = False

            if new_number and new_number != item.item_number:
                item.item_number = new_number
                changed = True
            elif normalized_number and normalized_number != item.item_number:
                item.item_number = normalized_number
                changed = True
            if new_name and new_name != item.name:
                item.name = new_name
                changed = True
            if new_units != item.unit:
                item.unit = new_units
                changed = True
            if item.package:
                item.package = ''
                changed = True

            if changed:
                item.save()
                fixed += 1
                self.stdout.write(self.style.SUCCESS(f'fixed «{item.name}» / {item.item_number}'))

        self.stdout.write(
            self.style.SUCCESS(
                f'done: {fixed} fixed, {merged} merged into siblings, {deleted} orphans removed'
            )
        )
