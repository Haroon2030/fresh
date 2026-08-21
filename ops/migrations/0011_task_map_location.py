from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0010_whatsapp_role_contact'),
    ]

    operations = [
        migrations.AlterField(
            model_name='task',
            name='branch',
            field=models.CharField(blank=True, max_length=255, verbose_name='موقع الفرع'),
        ),
        migrations.AddField(
            model_name='task',
            name='location_lat',
            field=models.DecimalField(
                blank=True,
                decimal_places=7,
                max_digits=10,
                null=True,
                verbose_name='خط العرض',
            ),
        ),
        migrations.AddField(
            model_name='task',
            name='location_lng',
            field=models.DecimalField(
                blank=True,
                decimal_places=7,
                max_digits=10,
                null=True,
                verbose_name='خط الطول',
            ),
        ),
    ]
