from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0020_branch_is_default'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplyorder',
            name='branch',
            field=models.CharField(blank=True, default='', max_length=150, verbose_name='الفرع'),
        ),
    ]
