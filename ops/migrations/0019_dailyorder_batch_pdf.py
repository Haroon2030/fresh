from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0018_evolutionconfig'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailyorder',
            name='batch_number',
            field=models.CharField(blank=True, db_index=True, max_length=20, verbose_name='رقم الملف'),
        ),
        migrations.AddField(
            model_name='dailyorder',
            name='public_token',
            field=models.CharField(blank=True, db_index=True, max_length=64, verbose_name='رمز تحميل PDF'),
        ),
    ]
