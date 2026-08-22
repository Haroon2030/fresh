"""Ensure critical ops columns exist (safety net if migrate was skipped)."""
from django.core.management.base import BaseCommand
from django.db import connection


TABLE_COLUMNS = {
    'ops_dailysupplydistribution': [
        ('batch_number', "varchar(20) NOT NULL DEFAULT ''"),
        ('public_token', "varchar(64) NOT NULL DEFAULT ''"),
    ],
    'ops_distributionvariance': [
        ('batch_number', "varchar(20) NOT NULL DEFAULT ''"),
        ('public_token', "varchar(64) NOT NULL DEFAULT ''"),
    ],
    'ops_supplyorder': [
        ('public_token', "varchar(64) NOT NULL DEFAULT ''"),
    ],
}


class Command(BaseCommand):
    help = 'Ensure ops batch_number columns exist on production DBs'

    def handle(self, *args, **options):
        vendor = connection.vendor
        with connection.cursor() as cursor:
            for table, cols in TABLE_COLUMNS.items():
                try:
                    existing = {
                        c.name
                        for c in connection.introspection.get_table_description(cursor, table)
                    }
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f'skip {table}: {exc}'))
                    continue
                for name, ddl in cols:
                    if name in existing:
                        self.stdout.write(f'OK {table}.{name}')
                        continue
                    if vendor == 'mysql':
                        sql = f'ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}'
                    elif vendor == 'postgresql':
                        sql = f'ALTER TABLE "{table}" ADD COLUMN "{name}" varchar(20) NOT NULL DEFAULT \'\''
                    else:
                        sql = f'ALTER TABLE "{table}" ADD COLUMN "{name}" varchar(20) NOT NULL DEFAULT \'\''
                    self.stdout.write(self.style.WARNING(f'ADD {table}.{name}'))
                    cursor.execute(sql)
                    self.stdout.write(self.style.SUCCESS(f'added {table}.{name}'))
