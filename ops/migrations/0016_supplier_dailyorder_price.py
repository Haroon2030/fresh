from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0015_dailyorder'),
    ]

    operations = [
        migrations.CreateModel(
            name='Supplier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150, unique=True, verbose_name='اسم المورد')),
                ('is_active', models.BooleanField(default=True, verbose_name='نشط')),
                ('sort_order', models.PositiveSmallIntegerField(default=0, verbose_name='الترتيب')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'مورد',
                'verbose_name_plural': 'الموردون',
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.AddField(
            model_name='dailyorder',
            name='supplier',
            field=models.CharField(blank=True, max_length=150, verbose_name='المورد'),
        ),
        migrations.AddField(
            model_name='dailyorder',
            name='unit_price',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='السعر'),
        ),
    ]
