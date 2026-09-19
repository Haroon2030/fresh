from django.db import migrations


DEFAULT_ACCOUNTS = [
    ('5101', 'تكلفة بضاعة مباعة — خضار', 10),
    ('5102', 'تسوية فروقات تكاليف', 20),
    ('1201', 'مخزون خضار وفاكهة', 30),
]


def seed_accounts(apps, schema_editor):
    AccountingAccount = apps.get_model('ops', 'AccountingAccount')
    for code, name, sort_order in DEFAULT_ACCOUNTS:
        AccountingAccount.objects.get_or_create(
            code=code,
            defaults={'name': name, 'sort_order': sort_order, 'is_active': True},
        )


def unseed_accounts(apps, schema_editor):
    AccountingAccount = apps.get_model('ops', 'AccountingAccount')
    CostSettlement = apps.get_model('ops', 'CostSettlement')
    for code, _, _ in DEFAULT_ACCOUNTS:
        acc = AccountingAccount.objects.filter(code=code).first()
        if not acc:
            continue
        if CostSettlement.objects.filter(accounting_account_id=acc.pk).exists():
            continue
        acc.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0035_accountingaccount_costsettlement'),
    ]

    operations = [
        migrations.RunPython(seed_accounts, unseed_accounts),
    ]
