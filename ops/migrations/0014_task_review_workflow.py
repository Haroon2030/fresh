import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0013_branch'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='response_text',
            field=models.TextField(blank=True, verbose_name='رد الموظف'),
        ),
        migrations.AddField(
            model_name='task',
            name='response_submitted_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت إرسال الرد'),
        ),
        migrations.AddField(
            model_name='task',
            name='review_note',
            field=models.TextField(blank=True, verbose_name='ملاحظة المراجعة'),
        ),
        migrations.AddField(
            model_name='task',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت المراجعة'),
        ),
        migrations.AddField(
            model_name='task',
            name='reviewed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reviewed_tasks',
                to=settings.AUTH_USER_MODEL,
                verbose_name='راجعه',
            ),
        ),
        migrations.AlterField(
            model_name='task',
            name='status',
            field=models.CharField(
                choices=[
                    ('todo', 'قيد الانتظار'),
                    ('in_progress', 'قيد التنفيذ'),
                    ('pending_review', 'بانتظار المراجعة'),
                    ('done', 'مكتمل'),
                ],
                default='todo',
                max_length=20,
                verbose_name='الحالة',
            ),
        ),
        migrations.CreateModel(
            name='TaskResponsePhoto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.FileField(upload_to='task_responses/%Y/%m/', verbose_name='صورة')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('task', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='response_photos',
                    to='ops.task',
                    verbose_name='المهمة',
                )),
            ],
            options={
                'verbose_name': 'صورة رد مهمة',
                'verbose_name_plural': 'صور ردود المهام',
                'ordering': ['uploaded_at'],
            },
        ),
    ]
