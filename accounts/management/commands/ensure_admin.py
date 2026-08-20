from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "إنشاء مدير العمليات مرة واحدة إن لم يكن موجوداً"

    def handle(self, *args, **options):
        username = "1"
        if User.objects.filter(username=username).exists():
            self.stdout.write("المدير موجود مسبقاً — تم التخطي")
            return

        user = User.objects.create_user(
            username=username,
            password="526400",
            first_name="مدير",
            last_name="العمليات",
            role=User.Role.MANAGER,
            is_staff=True,
            is_superuser=True,
        )
        self.stdout.write(self.style.SUCCESS(f"تم إنشاء المدير: {user.username}"))
