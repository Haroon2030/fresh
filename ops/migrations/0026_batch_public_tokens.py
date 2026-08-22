import secrets

from django.db import migrations, models


def backfill_tokens(apps, schema_editor):
    for model_name in ('SupplyOrder', 'DailySupplyDistribution', 'DistributionVariance'):
        Model = apps.get_model('ops', model_name)
        seen_batches = {}
        for row in Model.objects.all().order_by('id'):
            key = (row.batch_number or '').strip() or f'row-{row.pk}'
            if key not in seen_batches:
                seen_batches[key] = secrets.token_urlsafe(24)
            token = seen_batches[key]
            if not (row.public_token or '').strip():
                Model.objects.filter(pk=row.pk).update(public_token=token)


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0025_distribution_batch_numbers'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplyorder',
            name='public_token',
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=64, verbose_name='رمز PDF'),
        ),
        migrations.AddField(
            model_name='dailysupplydistribution',
            name='public_token',
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=64, verbose_name='رمز PDF'),
        ),
        migrations.AddField(
            model_name='distributionvariance',
            name='public_token',
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=64, verbose_name='رمز PDF'),
        ),
        migrations.RunPython(backfill_tokens, migrations.RunPython.noop),
    ]
