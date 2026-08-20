from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        MANAGER = 'manager', 'مدير العمليات'
        REPRESENTATIVE = 'representative', 'مندوب'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.REPRESENTATIVE,
        verbose_name='الدور',
    )

    class Meta:
        verbose_name = 'مستخدم'
        verbose_name_plural = 'المستخدمون'

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER

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
