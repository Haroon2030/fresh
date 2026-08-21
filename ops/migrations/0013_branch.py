from django.db import migrations, models


DEFAULT_BRANCHES = [
    'فرع المنصورة',
    'فرع الدمام',
    'فرع الخميس',
    'فرع سكاي مول',
    'فرع النسيم',
    'فرع الواحة',
    'فرع حائل',
    'فرع بريدة',
    'فرع بريدة 2',
]


def seed_branches(apps, schema_editor):
    Branch = apps.get_model('ops', 'Branch')
    for idx, name in enumerate(DEFAULT_BRANCHES, start=1):
        Branch.objects.get_or_create(
            name=name,
            defaults={'sort_order': idx, 'is_active': True},
        )


def unseed_branches(apps, schema_editor):
    Branch = apps.get_model('ops', 'Branch')
    Branch.objects.filter(name__in=DEFAULT_BRANCHES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0012_returnbatch_public_token'),
    ]

    operations = [
        migrations.CreateModel(
            name='Branch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150, unique=True, verbose_name='اسم الفرع')),
                ('is_active', models.BooleanField(default=True, verbose_name='نشط')),
                ('sort_order', models.PositiveSmallIntegerField(default=0, verbose_name='الترتيب')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'فرع',
                'verbose_name_plural': 'الفروع',
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.RunPython(seed_branches, unseed_branches),
    ]
