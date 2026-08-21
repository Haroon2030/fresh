from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ops', '0023_dailysupplydistribution'),
    ]

    operations = [
        migrations.CreateModel(
            name='DistributionVariance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('record_date', models.DateField(db_index=True, verbose_name='التاريخ')),
                ('variance_type', models.CharField(
                    choices=[('shortage', 'نقص'), ('excess', 'زيادة')],
                    max_length=20,
                    verbose_name='النوع',
                )),
                ('item_name', models.CharField(max_length=255, verbose_name='اسم الصنف')),
                ('item_number', models.CharField(blank=True, max_length=100, verbose_name='رقم الصنف')),
                ('branch', models.CharField(max_length=150, verbose_name='الفرع')),
                ('quantity', models.PositiveIntegerField(default=1, verbose_name='الكمية')),
                ('supplier', models.CharField(max_length=150, verbose_name='المورد')),
                ('notes', models.CharField(blank=True, max_length=255, verbose_name='ملاحظات')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'بانتظار تعميد المستلم'),
                        ('authorized', 'معتمد'),
                        ('rejected', 'مرفوض'),
                    ],
                    default='pending',
                    max_length=20,
                    verbose_name='الحالة',
                )),
                ('authorized_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت التعميد')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('authorized_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='authorized_variances',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='عمّد بواسطة',
                )),
                ('created_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='created_variances',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='أنشئ بواسطة',
                )),
            ],
            options={
                'verbose_name': 'نقص/زيادة توزيع',
                'verbose_name_plural': 'نقص التوزيع والزيادات',
                'ordering': ['-record_date', '-created_at'],
            },
        ),
    ]
