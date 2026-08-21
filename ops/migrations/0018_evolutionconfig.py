from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0017_supplier_phone_dailyorder_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='EvolutionConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('server_url', models.CharField(blank=True, max_length=255, verbose_name='رابط الخادم')),
                ('api_key', models.CharField(blank=True, max_length=255, verbose_name='مفتاح API')),
                ('instance_name', models.CharField(blank=True, max_length=100, verbose_name='اسم الانستانس')),
                ('notify_enabled', models.BooleanField(default=True, verbose_name='تفعيل الإشعارات')),
                ('verify_ssl', models.BooleanField(default=False, verbose_name='تحقق SSL')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'إعدادات Evolution',
                'verbose_name_plural': 'إعدادات Evolution',
            },
        ),
    ]
