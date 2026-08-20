import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def forwards_group_items(apps, schema_editor):
    ReturnBatch = apps.get_model('ops', 'ReturnBatch')
    ReturnRequest = apps.get_model('ops', 'ReturnRequest')
    for item in ReturnRequest.objects.filter(batch__isnull=True).order_by('id'):
        batch = ReturnBatch.objects.create(
            return_number=item.return_number or f'#RET-{item.pk:04d}',
            representative_id=item.representative_id,
            branch='غير محدد',
            created_by_id=item.created_by_id,
        )
        item.batch_id = batch.id
        item.save(update_fields=['batch_id'])


def backwards_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ops', '0007_return_rep_decision'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReturnBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('return_number', models.CharField(editable=False, max_length=20, unique=True)),
                ('branch', models.CharField(max_length=150, verbose_name='الفرع')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='created_return_batches',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='أنشئ بواسطة',
                )),
                ('representative', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='return_batches',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='المندوب',
                )),
            ],
            options={
                'verbose_name': 'ملف مرتجع',
                'verbose_name_plural': 'ملفات المرتجعات',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddField(
            model_name='returnrequest',
            name='batch',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='items',
                to='ops.returnbatch',
                verbose_name='ملف المرتجع',
            ),
        ),
        migrations.AlterField(
            model_name='returnrequest',
            name='return_number',
            field=models.CharField(blank=True, editable=False, max_length=20),
        ),
        migrations.AlterModelOptions(
            name='returnrequest',
            options={
                'ordering': ['id'],
                'verbose_name': 'صنف مرتجع',
                'verbose_name_plural': 'أصناف المرتجعات',
            },
        ),
        migrations.RunPython(forwards_group_items, backwards_noop),
    ]
