from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        SYSTEM_ADMIN = 'system_admin', 'مدير النظام'
        DEPT_MANAGER = 'dept_manager', 'مدير القسم'
        MANAGER = 'manager', 'مدير العمليات'
        REPRESENTATIVE = 'representative', 'المندوب'
        RECEIVER = 'receiver', 'المستلم'
        ACCOUNTANT = 'accountant', 'المحاسب'
        DATA = 'data', 'البيانات'

    MANAGEMENT_ROLES = {
        Role.SYSTEM_ADMIN,
        Role.DEPT_MANAGER,
        Role.MANAGER,
    }

    NOTIFY_ROLES = {
        Role.SYSTEM_ADMIN,
        Role.DEPT_MANAGER,
        Role.MANAGER,
        Role.ACCOUNTANT,
    }

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.REPRESENTATIVE,
        verbose_name='الدور',
    )
    whatsapp = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='واتساب',
        help_text='رقم دولي بدون + مثل 9665xxxxxxxx',
    )

    class Meta:
        verbose_name = 'مستخدم'
        verbose_name_plural = 'المستخدمون'

    @property
    def is_manager(self):
        """صلاحيات إدارية (مستخدمون، مهام، اعتمادات)."""
        return self.role in self.MANAGEMENT_ROLES

    @property
    def is_system_admin(self):
        return self.role == self.Role.SYSTEM_ADMIN

    @property
    def is_representative(self):
        return self.role == self.Role.REPRESENTATIVE

    @property
    def display_name(self):
        full = self.get_full_name().strip()
        return full or self.username

    @property
    def initials(self):
        name = self.display_name
        parts = name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return name[:1].upper() if name else '?'
