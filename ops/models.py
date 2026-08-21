from django.conf import settings
from django.db import models
from django.db.models import Max


class SupplyOrder(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'قيد الانتظار'
        COMPLETED = 'completed', 'مكتمل'
        REJECTED = 'rejected', 'مرفوض'

    order_number = models.CharField(max_length=20, unique=True, editable=False)
    representative = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='supply_orders',
        verbose_name='المندوب',
    )
    item_name = models.CharField(max_length=255, verbose_name='الاسم')
    item_number = models.CharField(max_length=100, blank=True, verbose_name='رقم الصنف')
    unit = models.CharField(max_length=50, blank=True, verbose_name='الوحدة')
    package = models.CharField(max_length=100, blank=True, verbose_name='العبوة')
    quantity = models.PositiveIntegerField(default=1, verbose_name='الكمية')
    expected_date = models.DateField(null=True, blank=True, verbose_name='التاريخ المتوقع')
    notes = models.TextField(blank=True, verbose_name='ملاحظات')
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name='السعر',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='الحالة',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_supply_orders',
        verbose_name='أنشئ بواسطة',
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_supply_orders',
        verbose_name='راجع بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'طلب توريد'
        verbose_name_plural = 'طلبات التوريد'

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        if not self.order_number:
            last = SupplyOrder.objects.aggregate(Max('id'))['id__max'] or 0
            self.order_number = f'#ORD-{last + 1:03d}'
        super().save(*args, **kwargs)

    @property
    def total_amount(self):
        return self.quantity * self.unit_price


class ReturnBatch(models.Model):
    """ملف مرتجع واحد يحتوي عدة أصناف."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'قيد الانتظار'
        ACCEPTED = 'accepted', 'مقبول'
        REJECTED = 'rejected', 'مرفوض'
        MIXED = 'mixed', 'متعدد الحالات'

    return_number = models.CharField(max_length=20, unique=True, editable=False)
    representative = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='return_batches',
        verbose_name='المندوب',
    )
    branch = models.CharField(max_length=150, verbose_name='الفرع')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_return_batches',
        verbose_name='أنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'ملف مرتجع'
        verbose_name_plural = 'ملفات المرتجعات'

    def __str__(self):
        return self.return_number

    def save(self, *args, **kwargs):
        if not self.return_number:
            last = ReturnBatch.objects.aggregate(Max('id'))['id__max'] or 0
            self.return_number = f'#RET-{last + 1:04d}'
        super().save(*args, **kwargs)

    @property
    def items_count(self):
        return self.items.count()

    @property
    def display_status(self):
        statuses = list(self.items.values_list('status', flat=True))
        if not statuses:
            return self.Status.PENDING
        unique = set(statuses)
        if unique == {ReturnRequest.Status.PENDING}:
            return self.Status.PENDING
        if unique == {ReturnRequest.Status.ACCEPTED}:
            return self.Status.ACCEPTED
        if unique == {ReturnRequest.Status.REJECTED}:
            return self.Status.REJECTED
        if ReturnRequest.Status.PENDING in unique:
            return self.Status.PENDING
        return self.Status.MIXED

    def get_display_status_display(self):
        return dict(self.Status.choices).get(self.display_status, self.display_status)


class ReturnRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'قيد الانتظار'
        ACCEPTED = 'accepted', 'تم القبول'
        REJECTED = 'rejected', 'مرفوض'

    class ReturnType(models.TextChoices):
        UNACCEPTABLE = 'unacceptable', 'غير مقبول'
        EXCHANGE = 'exchange', 'تبديل'
        RETURN = 'return', 'مرتجع'

    batch = models.ForeignKey(
        ReturnBatch,
        on_delete=models.CASCADE,
        related_name='items',
        null=True,
        blank=True,
        verbose_name='ملف المرتجع',
    )
    return_number = models.CharField(max_length=20, blank=True, editable=False)
    representative = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='return_requests',
        verbose_name='المندوب',
    )
    item_name = models.CharField(max_length=255, verbose_name='الاسم')
    item_number = models.CharField(max_length=100, blank=True, verbose_name='رقم الصنف')
    unit = models.CharField(max_length=50, blank=True, verbose_name='الوحدة')
    package = models.CharField(max_length=100, blank=True, verbose_name='العبوة')
    quantity = models.PositiveIntegerField(default=1, verbose_name='الكمية')
    return_type = models.CharField(
        max_length=20,
        choices=ReturnType.choices,
        default=ReturnType.RETURN,
        verbose_name='نوع المرتجع',
    )
    reason = models.TextField(verbose_name='سبب الإرجاع')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='الحالة',
    )

    class RepDecision(models.TextChoices):
        PENDING = 'pending', 'بانتظار التعميد'
        AUTHORIZED = 'authorized', 'معتمد'
        REJECTED = 'rejected', 'مرفوض من المندوب'

    rep_decision = models.CharField(
        max_length=20,
        choices=RepDecision.choices,
        default=RepDecision.PENDING,
        verbose_name='تعميد المندوب',
    )
    rep_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rep_decided_returns',
        verbose_name='عمّده / رفضه',
    )
    rep_decided_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ قرار المندوب')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_return_requests',
        verbose_name='أنشئ بواسطة',
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_return_requests',
        verbose_name='راجع بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'صنف مرتجع'
        verbose_name_plural = 'أصناف المرتجعات'

    def __str__(self):
        if self.batch_id:
            return f'{self.batch.return_number} — {self.item_name}'
        return self.item_name or f'Return #{self.pk}'

    def save(self, *args, **kwargs):
        # الرقم على مستوى الملف فقط؛ نترك الحقل للتوافق مع البيانات القديمة
        if self.batch_id and not self.return_number:
            self.return_number = self.batch.return_number
        elif not self.return_number and not self.batch_id:
            last = ReturnRequest.objects.aggregate(Max('id'))['id__max'] or 0
            self.return_number = f'#RET-{last + 1:04d}'
        super().save(*args, **kwargs)


class Task(models.Model):
    class Priority(models.TextChoices):
        URGENT = 'urgent', 'عاجل'
        MEDIUM = 'medium', 'متوسط'
        NORMAL = 'normal', 'عادي'

    class Status(models.TextChoices):
        TODO = 'todo', 'قيد الانتظار'
        IN_PROGRESS = 'in_progress', 'قيد التنفيذ'
        DONE = 'done', 'مكتمل'

    title = models.CharField(max_length=255, verbose_name='العنوان')
    description = models.TextField(blank=True, verbose_name='الوصف')
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.NORMAL,
        verbose_name='الأولوية',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TODO,
        verbose_name='الحالة',
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tasks',
        verbose_name='معيّن إلى',
    )
    branch = models.CharField(max_length=255, blank=True, verbose_name='موقع الفرع')
    location_lat = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        verbose_name='خط العرض',
    )
    location_lng = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        verbose_name='خط الطول',
    )
    visit_details = models.TextField(blank=True, verbose_name='تفاصيل الزيارة')
    public_token = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        blank=True,
        verbose_name='رمز الرابط',
    )
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الإنجاز')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_tasks',
        verbose_name='أنشئ بواسطة',
    )
    due_at = models.DateTimeField(null=True, blank=True, verbose_name='الموعد')
    progress = models.PositiveSmallIntegerField(default=0, verbose_name='التقدم')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'مهمة'
        verbose_name_plural = 'المهام'

    def __str__(self):
        return self.title

    def ensure_public_token(self):
        if not self.public_token:
            import secrets
            self.public_token = secrets.token_urlsafe(24)

    def save(self, *args, **kwargs):
        self.ensure_public_token()
        super().save(*args, **kwargs)

    def mark_done(self):
        from django.utils import timezone
        self.status = self.Status.DONE
        self.progress = 100
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'progress', 'completed_at', 'updated_at'])

    @property
    def is_overdue(self):
        from django.utils import timezone
        if self.due_at and self.status != self.Status.DONE:
            return self.due_at < timezone.now()
        return False

    @property
    def maps_url(self):
        if self.location_lat is None or self.location_lng is None:
            return ''
        return (
            f'https://www.google.com/maps?q={self.location_lat},{self.location_lng}'
        )


class CatalogItem(models.Model):
    name = models.CharField(max_length=255, verbose_name='الاسم')
    item_number = models.CharField(max_length=100, unique=True, verbose_name='رقم الصنف')
    unit = models.CharField(max_length=50, blank=True, verbose_name='الوحدة')
    package = models.CharField(max_length=100, blank=True, verbose_name='العبوة')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'صنف'
        verbose_name_plural = 'الأصناف'

    def __str__(self):
        return f'{self.name} ({self.item_number})'


class WhatsAppRoleContact(models.Model):
    """رقم واتساب مرتبط بدور معيّن لاستلام الإشعارات."""

    ROLE_CHOICES = [
        ('system_admin', 'مدير النظام'),
        ('dept_manager', 'مدير القسم'),
        ('manager', 'مدير العمليات'),
        ('representative', 'المندوب'),
        ('receiver', 'المستلم'),
        ('accountant', 'المحاسب'),
        ('data', 'البيانات'),
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        unique=True,
        verbose_name='الدور',
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='رقم واتساب',
        help_text='صيغة دولية بدون + مثل 9665xxxxxxxx',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'رقم واتساب للدور'
        verbose_name_plural = 'أرقام واتساب للأدوار'
        ordering = ['role']

    def __str__(self):
        return f'{self.get_role_display()}: {self.phone or "—"}'
