from django.db import migrations, models


def backfill_tokens(apps, schema_editor):
    import secrets
    ReturnBatch = apps.get_model('ops', 'ReturnBatch')
    for batch in ReturnBatch.objects.all():
        if not (batch.public_token or '').strip():
            batch.public_token = secrets.token_urlsafe(24)
            batch.save(update_fields=['public_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0011_task_map_location'),
    ]

    operations = [
        migrations.AddField(
            model_name='returnbatch',
            name='public_token',
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=64,
                unique=True,
                null=True,
                verbose_name='رمز تحميل PDF',
            ),
        ),
        migrations.RunPython(backfill_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='returnbatch',
            name='public_token',
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=64,
                unique=True,
                verbose_name='رمز تحميل PDF',
            ),
        ),
    ]
