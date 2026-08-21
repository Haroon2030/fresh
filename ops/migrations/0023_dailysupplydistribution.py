from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ops', '0022_supplyorder_batch_supplier'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailySupplyDistribution',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('distribution_date', models.DateField(db_index=True, verbose_name='تاريخ التوزيع')),
                ('item_name', models.CharField(max_length=255, verbose_name='اسم الصنف')),
                ('item_number', models.CharField(blank=True, max_length=100, verbose_name='رقم الصنف')),
                ('branch', models.CharField(max_length=150, verbose_name='اسم الفرع')),
                ('quantity', models.PositiveIntegerField(default=1, verbose_name='الكمية الموزعة')),
                ('notes', models.CharField(blank=True, max_length=255, verbose_name='ملاحظات')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    on_delete=models.deletion.PROTECT,
                    related_name='created_distributions',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='أنشئ بواسطة',
                )),
            ],
            options={
                'verbose_name': 'توزيع توريد يومي',
                'verbose_name_plural': 'توزيع التوريد اليومي',
                'ordering': ['-distribution_date', '-created_at'],
            },
        ),
    ]
