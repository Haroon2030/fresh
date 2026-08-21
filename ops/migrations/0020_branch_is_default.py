from django.db import migrations, models


def seed_default_branch(apps, schema_editor):
    Branch = apps.get_model('ops', 'Branch')
    if Branch.objects.filter(is_default=True).exists():
        return
    first = Branch.objects.filter(is_active=True).order_by('sort_order', 'name').first()
    if first:
        first.is_default = True
        first.save(update_fields=['is_default'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0019_dailyorder_batch_pdf'),
    ]

    operations = [
        migrations.AddField(
            model_name='branch',
            name='is_default',
            field=models.BooleanField(
                default=False,
                help_text='يُختار تلقائياً في نماذج المرتجعات والطلبيات والمهام.',
                verbose_name='افتراضي',
            ),
        ),
        migrations.RunPython(seed_default_branch, noop_reverse),
    ]
