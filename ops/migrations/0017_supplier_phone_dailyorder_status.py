import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0016_supplier_dailyorder_price'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='supplier',
            name='phone',
            field=models.CharField(
                blank=True,
                help_text='صيغة دولية بدون + مثل 9665xxxxxxxx — لإشعار واتساب بعد اعتماد الطلب',
                max_length=20,
                verbose_name='رقم الجوال',
            ),
        ),
        migrations.AddField(
            model_name='dailyorder',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'قيد الاعتماد'),
                    ('approved', 'معتمد'),
                    ('rejected', 'مرفوض'),
                ],
                default='pending',
                max_length=20,
                verbose_name='الحالة',
            ),
        ),
        migrations.AddField(
            model_name='dailyorder',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت الاعتماد'),
        ),
        migrations.AddField(
            model_name='dailyorder',
            name='reviewed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reviewed_daily_orders',
                to=settings.AUTH_USER_MODEL,
                verbose_name='اعتمد بواسطة',
            ),
        ),
    ]
