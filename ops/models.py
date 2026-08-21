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
    public_token = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        blank=True,
        verbose_name='رمز تحميل PDF',
    )
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

    def ensure_public_token(self):
        if not self.public_token:
            import secrets
            self.public_token = secrets.token_urlsafe(24)

    def save(self, *args, **kwargs):
        if not self.return_number:
            last = ReturnBatch.objects.aggregate(Max('id'))['id__max'] or 0
            self.return_number = f'#RET-{last + 1:04d}'
        self.ensure_public_token()
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
        PENDING_REVIEW = 'pending_review', 'بانتظار المراجعة'
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
    response_text = models.TextField(blank=True, verbose_name='رد الموظف')
    response_submitted_at = models.DateTimeField(
        null=True, blank=True, verbose_name='وقت إرسال الرد',
    )
    review_note = models.TextField(blank=True, verbose_name='ملاحظة المراجعة')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_tasks',
        verbose_name='راجعه',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت المراجعة')
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

    def submit_for_review(self, text: str):
        from django.utils import timezone
        self.response_text = (text or '').strip()
        self.response_submitted_at = timezone.now()
        self.status = self.Status.PENDING_REVIEW
        self.progress = 80
        self.completed_at = None
        self.save(update_fields=[
            'response_text', 'response_submitted_at', 'status',
            'progress', 'completed_at', 'updated_at',
        ])

    def approve_response(self, reviewer, note: str = ''):
        from django.utils import timezone
        self.review_note = (note or '').strip()
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.status = self.Status.DONE
        self.progress = 100
        self.completed_at = timezone.now()
        self.save(update_fields=[
            'review_note', 'reviewed_by', 'reviewed_at',
            'status', 'progress', 'completed_at', 'updated_at',
        ])

    def reject_response(self, reviewer, note: str = ''):
        from django.utils import timezone
        self.review_note = (note or '').strip()
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.status = self.Status.IN_PROGRESS
        self.progress = 45
        self.completed_at = None
        self.save(update_fields=[
            'review_note', 'reviewed_by', 'reviewed_at',
            'status', 'progress', 'completed_at', 'updated_at',
        ])

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


class TaskResponsePhoto(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='response_photos',
        verbose_name='المهمة',
    )
    image = models.FileField(upload_to='task_responses/%Y/%m/', verbose_name='صورة')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']
        verbose_name = 'صورة رد مهمة'
        verbose_name_plural = 'صور ردود المهام'

    def __str__(self):
        return f'صورة #{self.pk} — {self.task_id}'


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


class Branch(models.Model):
    """فروع التشغيل — تُستخدم في مهام الزيارة وغيرها."""

    name = models.CharField(max_length=150, unique=True, verbose_name='اسم الفرع')
    is_active = models.BooleanField(default=True, verbose_name='نشط')
    is_default = models.BooleanField(
        default=False,
        verbose_name='افتراضي',
        help_text='يُختار تلقائياً في نماذج المرتجعات والطلبيات والمهام.',
    )
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='الترتيب')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'فرع'
        verbose_name_plural = 'الفروع'

    def __str__(self):
        return self.name

    @classmethod
    def active_names(cls):
        return list(cls.objects.filter(is_active=True).order_by('sort_order', 'name').values_list('name', flat=True))

    @classmethod
    def default_name(cls):
        """اسم الفرع الافتراضي النشط من التهيئة (أو أول فرع نشط إن لم يُحدَّد)."""
        name = (
            cls.objects.filter(is_active=True, is_default=True)
            .order_by('sort_order', 'name')
            .values_list('name', flat=True)
            .first()
        )
        if name:
            return name
        return (
            cls.objects.filter(is_active=True)
            .order_by('sort_order', 'name')
            .values_list('name', flat=True)
            .first()
            or ''
        )

    def set_as_default(self):
        """اجعل هذا الفرع هو الافتراضي الوحيد."""
        type(self).objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        if not self.is_default or not self.is_active:
            self.is_default = True
            self.is_active = True
            self.save(update_fields=['is_default', 'is_active', 'updated_at'])


class Supplier(models.Model):
    """الموردون — تُستخدم في طلبات الشراء اليومية."""

    name = models.CharField(max_length=150, unique=True, verbose_name='اسم المورد')
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='رقم الجوال',
        help_text='صيغة دولية بدون + مثل 9665xxxxxxxx — لإشعار واتساب بعد اعتماد الطلب',
    )
    is_active = models.BooleanField(default=True, verbose_name='نشط')
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='الترتيب')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'مورد'
        verbose_name_plural = 'الموردون'

    def __str__(self):
        return self.name

    @classmethod
    def active_names(cls):
        return list(cls.objects.filter(is_active=True).order_by('sort_order', 'name').values_list('name', flat=True))

    def normalized_phone(self) -> str:
        from ops.whatsapp import normalize_whatsapp
        return normalize_whatsapp(self.phone or '')


class DailyOrder(models.Model):
    """تسجيل طلبية يومية (صف واحد لكل صنف)."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'قيد الاعتماد'
        APPROVED = 'approved', 'معتمد'
        REJECTED = 'rejected', 'مرفوض'

    order_number = models.CharField(max_length=20, unique=True, editable=False)
    batch_number = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        verbose_name='رقم الملف',
    )
    public_token = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        verbose_name='رمز تحميل PDF',
    )
    order_date = models.DateField(verbose_name='تاريخ الطلبية')
    item_number = models.CharField(max_length=100, blank=True, verbose_name='رقم الصنف')
    item_name = models.CharField(max_length=255, verbose_name='اسم الصنف')
    quantity = models.PositiveIntegerField(default=1, verbose_name='الكمية')
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name='السعر',
    )
    representative = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='daily_orders',
        verbose_name='المندوب',
    )
    branch = models.CharField(max_length=150, verbose_name='الفرع')
    supplier = models.CharField(max_length=150, blank=True, verbose_name='المورد')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='الحالة',
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_daily_orders',
        verbose_name='اعتمد بواسطة',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت الاعتماد')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_daily_orders',
        verbose_name='أنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-order_date', '-created_at']
        verbose_name = 'طلبية يومية'
        verbose_name_plural = 'الطلبيات اليومية'

    def __str__(self):
        return f'{self.order_number} — {self.item_name}'

    @property
    def line_total(self):
        return self.quantity * self.unit_price

    def save(self, *args, **kwargs):
        if not self.order_date:
            from django.utils import timezone
            self.order_date = timezone.localdate()
        if not self.order_number:
            last = DailyOrder.objects.aggregate(Max('id'))['id__max'] or 0
            self.order_number = f'#DAY-{last + 1:04d}'
        if not self.public_token:
            import secrets
            self.public_token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)

    def ensure_public_token(self):
        if not self.public_token:
            import secrets
            self.public_token = secrets.token_urlsafe(24)


class EvolutionConfig(models.Model):
    """إعدادات Evolution المحفوظة في قاعدة البيانات (بديل عند فشل متغيرات Dokploy)."""

    server_url = models.CharField(max_length=255, blank=True, verbose_name='رابط الخادم')
    api_key = models.CharField(max_length=255, blank=True, verbose_name='مفتاح API')
    instance_name = models.CharField(max_length=100, blank=True, verbose_name='اسم الانستانس')
    notify_enabled = models.BooleanField(default=True, verbose_name='تفعيل الإشعارات')
    verify_ssl = models.BooleanField(default=False, verbose_name='تحقق SSL')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إعدادات Evolution'
        verbose_name_plural = 'إعدادات Evolution'

    def __str__(self):
        return self.instance_name or 'Evolution'

    @classmethod
    def get_solo(cls):
        obj = cls.objects.order_by('pk').first()
        if obj is None:
            obj = cls.objects.create()
        return obj


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
