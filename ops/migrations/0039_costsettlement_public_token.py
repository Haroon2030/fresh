# Generated manually for CostSettlement public_token (WhatsApp PDF link)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0038_restore_cost_settlement'),
    ]

    operations = [
        migrations.AddField(
            model_name='costsettlement',
            name='public_token',
            field=models.CharField(
                blank=True,
                db_index=True,
                editable=False,
                max_length=64,
                verbose_name='رمز PDF',
            ),
        ),
    ]
