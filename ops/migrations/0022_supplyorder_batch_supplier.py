from django.db import migrations, models


def backfill_batches(apps, schema_editor):
    SupplyOrder = apps.get_model('ops', 'SupplyOrder')
    for order in SupplyOrder.objects.all().iterator():
        updates = []
        if not (order.batch_number or '').strip():
            order.batch_number = order.order_number or f'#SUP-{order.pk}'
            updates.append('batch_number')
        if updates:
            order.save(update_fields=updates)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0021_supplyorder_branch'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplyorder',
            name='batch_number',
            field=models.CharField(blank=True, db_index=True, max_length=20, verbose_name='رقم الملف'),
        ),
        migrations.AddField(
            model_name='supplyorder',
            name='supplier',
            field=models.CharField(blank=True, default='', max_length=150, verbose_name='المورد'),
        ),
        migrations.RunPython(backfill_batches, noop),
    ]
