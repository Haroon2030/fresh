from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from ops.models import ReturnRequest, SupplyOrder, Task

User = get_user_model()


class Command(BaseCommand):
    help = 'إنشاء بيانات تجريبية لبوابة عمليات الفرش'

    def handle(self, *args, **options):
        manager, created = User.objects.get_or_create(
            username='ahmed',
            defaults={
                'first_name': 'أحمد',
                'last_name': 'محمد',
                'role': User.Role.MANAGER,
                'is_staff': True,
            },
        )
        if created or not manager.check_password('demo123'):
            manager.set_password('demo123')
            manager.role = User.Role.MANAGER
            manager.is_staff = True
            manager.save()

        reps_data = [
            ('khaled', 'خالد', 'عبدالله'),
            ('mohammed', 'محمد', 'سالم'),
            ('saad', 'سعد', 'فهد'),
        ]
        reps = []
        for username, first, last in reps_data:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'role': User.Role.REPRESENTATIVE,
                },
            )
            if created or not user.check_password('demo123'):
                user.set_password('demo123')
                user.role = User.Role.REPRESENTATIVE
                user.save()
            reps.append(user)

        khaled, mohammed, saad = reps
        now = timezone.now()

        if not SupplyOrder.objects.exists():
            samples = [
                (khaled, 'معدات تغليف - لفة كبيرة', 'PKG-001', 'لفة', 'كرتون', 15, SupplyOrder.Status.COMPLETED, Decimal('120')),
                (mohammed, 'صناديق شحن (متوسطة)', 'BOX-050', 'قطعة', 'ربطة', 500, SupplyOrder.Status.PENDING, Decimal('8')),
                (saad, 'أشرطة لاصقة (درزينة)', 'TAP-012', 'درزينة', 'علبة', 10, SupplyOrder.Status.REJECTED, Decimal('25')),
                (khaled, 'أكياس فراغية', 'BAG-200', 'قطعة', 'كيس', 200, SupplyOrder.Status.PENDING, Decimal('3.5')),
                (mohammed, 'منصات خشبية', 'PLT-040', 'قطعة', 'طبلية', 40, SupplyOrder.Status.COMPLETED, Decimal('85')),
            ]
            for rep, item, num, unit, package, qty, status, price in samples:
                order = SupplyOrder(
                    representative=rep,
                    item_name=item,
                    item_number=num,
                    unit=unit,
                    package=package,
                    quantity=qty,
                    status=status,
                    unit_price=price,
                    created_by=rep,
                    expected_date=(now + timedelta(days=5)).date(),
                )
                if status != SupplyOrder.Status.PENDING:
                    order.reviewed_by = manager
                order.save()

        if not ReturnRequest.objects.exists():
            r1 = ReturnRequest(
                representative=khaled,
                item_name='كرسي مكتب مريح - أسود',
                item_number='CHR-099-BLK',
                unit='قطعة',
                package='كرتون',
                quantity=2,
                reason='خدوش ظاهرة على المسند الأيمن',
                status=ReturnRequest.Status.PENDING,
                created_by=khaled,
            )
            r1.save()
            r2 = ReturnRequest(
                representative=mohammed,
                item_name='طاولة اجتماعات 6 أشخاص',
                item_number='DSK-300-WHT',
                unit='قطعة',
                package='طبلية',
                quantity=1,
                reason='خطأ في القياسات المطلوبة',
                status=ReturnRequest.Status.ACCEPTED,
                created_by=mohammed,
                reviewed_by=manager,
            )
            r2.save()

        if not Task.objects.exists():
            Task.objects.create(
                title='تجهيز طلبية مستودع الرياض',
                description='تجميع وتغليف 50 وحدة من الصنف A لفرع الرياض. التأكد من سلامة التغليف قبل الشحن.',
                priority=Task.Priority.URGENT,
                status=Task.Status.TODO,
                assigned_to=khaled,
                created_by=manager,
                due_at=now.replace(hour=14, minute=0, second=0, microsecond=0),
            )
            Task.objects.create(
                title='فحص شاحنة التوصيل #402',
                description='إجراء الفحص الدوري الأسبوعي للشاحنة قبل انطلاقها لخط السير الغربي.',
                priority=Task.Priority.MEDIUM,
                status=Task.Status.TODO,
                assigned_to=saad,
                created_by=manager,
                due_at=now + timedelta(days=1),
            )
            Task.objects.create(
                title='جرد المخزون - القسم ب',
                description='جرد ومطابقة الأرصدة الفعلية مع النظام للقسم ب (المواد الاستهلاكية).',
                priority=Task.Priority.URGENT,
                status=Task.Status.IN_PROGRESS,
                assigned_to=mohammed,
                created_by=manager,
                progress=45,
                due_at=now - timedelta(hours=2),
            )
            Task.objects.create(
                title='استلام توريدة المورد X',
                description='استلام ومطابقة الفواتير للشحنة الواردة صباح اليوم.',
                priority=Task.Priority.NORMAL,
                status=Task.Status.DONE,
                assigned_to=khaled,
                created_by=manager,
                progress=100,
            )

        self.stdout.write(self.style.SUCCESS(
            'تم إنشاء البيانات التجريبية.\n'
            'مدير: ahmed / demo123\n'
            'مناديب: khaled, mohammed, saad / demo123'
        ))
