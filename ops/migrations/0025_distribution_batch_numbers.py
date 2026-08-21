from django.db import migrations, models


def backfill_batches(apps, schema_editor):
    DailySupplyDistribution = apps.get_model('ops', 'DailySupplyDistribution')
    DistributionVariance = apps.get_model('ops', 'DistributionVariance')

    for row in DailySupplyDistribution.objects.all().iterator():
        if not (row.batch_number or '').strip():
            row.batch_number = f'#DIST-{row.pk:04d}'
            row.save(update_fields=['batch_number'])

    for row in DistributionVariance.objects.all().iterator():
        if not (row.batch_number or '').strip():
            row.batch_number = f'#VAR-{row.pk:04d}'
            row.save(update_fields=['batch_number'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0024_distributionvariance'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailysupplydistribution',
            name='batch_number',
            field=models.CharField(blank=True, db_index=True, max_length=20, verbose_name='رقم الملف'),
        ),
        migrations.AddField(
            model_name='distributionvariance',
            name='batch_number',
            field=models.CharField(blank=True, db_index=True, max_length=20, verbose_name='رقم الملف'),
        ),
        migrations.RunPython(backfill_batches, noop),
    ]
