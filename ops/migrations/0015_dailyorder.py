import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0014_task_review_workflow'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order_number', models.CharField(editable=False, max_length=20, unique=True)),
                ('order_date', models.DateField(verbose_name='تاريخ الطلبية')),
                ('item_number', models.CharField(blank=True, max_length=100, verbose_name='رقم الصنف')),
                ('item_name', models.CharField(max_length=255, verbose_name='اسم الصنف')),
                ('quantity', models.PositiveIntegerField(default=1, verbose_name='الكمية')),
                ('branch', models.CharField(max_length=150, verbose_name='الفرع')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='created_daily_orders',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='أنشئ بواسطة',
                )),
                ('representative', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='daily_orders',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='المندوب',
                )),
            ],
            options={
                'verbose_name': 'طلبية يومية',
                'verbose_name_plural': 'الطلبيات اليومية',
                'ordering': ['-order_date', '-created_at'],
            },
        ),
    ]
