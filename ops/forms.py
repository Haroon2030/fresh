from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import ReturnRequest, SupplyOrder, Task

User = get_user_model()


class SupplyOrderForm(forms.ModelForm):
    class Meta:
        model = SupplyOrder
        fields = [
            'representative', 'item_name', 'item_number', 'unit', 'package',
            'quantity', 'expected_date', 'notes', 'unit_price',
        ]
        widgets = {
            'representative': forms.Select(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
            }),
            'item_name': forms.TextInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
                'placeholder': 'الاسم',
            }),
            'item_number': forms.TextInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
            }),
            'unit': forms.TextInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
            }),
            'package': forms.TextInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
                'min': '1',
                'placeholder': '0',
            }),
            'expected_date': forms.DateInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
                'type': 'date',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors resize-none',
                'rows': 3,
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
                'min': '0',
                'step': '0.01',
                'placeholder': '0',
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['representative'].queryset = User.objects.filter(is_active=True)
        self.fields['representative'].label = 'اسم المندوب'
        self.fields['representative'].empty_label = 'اختر المندوب...'
        self.fields['item_name'].label = 'الاسم'
        self.fields['item_number'].label = 'رقم الصنف'
        self.fields['unit'].label = 'الوحدة'
        self.fields['package'].label = 'العبوة'
        self.fields['quantity'].label = 'الكمية'
        self.fields['expected_date'].label = 'التاريخ المتوقع'
        self.fields['notes'].label = 'ملاحظات إضافية (اختياري)'
        self.fields['unit_price'].label = 'السعر (ر.س)'
        self.fields['item_number'].required = False
        self.fields['unit'].required = False
        self.fields['package'].required = False
        self.fields['notes'].required = False
        self.fields['expected_date'].required = False
        self.fields['unit_price'].required = False

        if user and user.is_representative:
            self.fields['representative'].initial = user
            self.fields['representative'].widget = forms.HiddenInput()
            self.fields['representative'].queryset = User.objects.filter(pk=user.pk)


class ReturnRequestForm(forms.ModelForm):
    class Meta:
        model = ReturnRequest
        fields = ['representative', 'item_name', 'item_number', 'unit', 'package', 'quantity', 'reason']
        widgets = {
            'representative': forms.Select(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
            }),
            'item_name': forms.TextInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
                'placeholder': 'الاسم',
            }),
            'item_number': forms.TextInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
                'placeholder': 'رقم الصنف',
            }),
            'unit': forms.TextInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
                'placeholder': 'الوحدة',
            }),
            'package': forms.TextInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
                'placeholder': 'العبوة',
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
                'min': '1',
            }),
            'reason': forms.Textarea(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors resize-none',
                'rows': 3,
                'placeholder': 'سبب الإرجاع...',
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['representative'].queryset = User.objects.filter(role=User.Role.REPRESENTATIVE)
        self.fields['representative'].label = 'اسم المندوب'
        self.fields['representative'].empty_label = 'اختر المندوب...'
        self.fields['item_name'].label = 'الاسم'
        self.fields['item_number'].label = 'رقم الصنف'
        self.fields['unit'].label = 'الوحدة'
        self.fields['package'].label = 'العبوة'
        self.fields['quantity'].label = 'الكمية'
        self.fields['reason'].label = 'سبب الإرجاع'
        self.fields['item_number'].required = False
        self.fields['unit'].required = False
        self.fields['package'].required = False

        if user and user.is_representative:
            self.fields['representative'].initial = user
            self.fields['representative'].widget = forms.HiddenInput()
            self.fields['representative'].queryset = User.objects.filter(pk=user.pk)


class TaskForm(forms.ModelForm):
    TITLE_CHOICES = [
        ('', 'اختر عنوان المهمة...'),
        ('زيارة فرع', 'زيارة فرع'),
        ('متابعة مرتجع', 'متابعة مرتجع'),
        ('متابعة توريد', 'متابعة توريد'),
        ('استلام بضاعة', 'استلام بضاعة'),
        ('جرد فرع', 'جرد فرع'),
        ('فحص جودة', 'فحص جودة'),
        ('تحصيل / متابعة مالية', 'تحصيل / متابعة مالية'),
        ('شكوى عميل', 'شكوى عميل'),
        ('صيانة / تجهيز', 'صيانة / تجهيز'),
        ('مهمة أخرى', 'مهمة أخرى'),
    ]

    title = forms.ChoiceField(
        choices=TITLE_CHOICES,
        label='العنوان',
        widget=forms.Select(attrs={
            'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors app-select',
        }),
    )
    branch = forms.ChoiceField(
        choices=[('', 'اختر الفرع...')],
        label='موقع الفرع',
        required=True,
        widget=forms.Select(attrs={
            'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors app-select',
            'id': 'id_branch',
        }),
    )

    class Meta:
        model = Task
        fields = [
            'title', 'description', 'priority', 'assigned_to',
            'branch', 'due_at',
        ]
        widgets = {
            'description': forms.Textarea(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors resize-none',
                'rows': 3,
                'placeholder': 'وصف عام للمهمة (اختياري)',
            }),
            'priority': forms.Select(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors app-select',
            }),
            'assigned_to': forms.Select(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors app-select',
            }),
            'due_at': forms.DateTimeInput(attrs={
                'class': 'w-full bg-surface border border-outline-variant rounded-lg py-2.5 px-3 focus:border-primary focus:ring-1 focus:ring-primary font-body-md text-body-md text-on-surface transition-colors',
                'type': 'datetime-local',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Branch

        self.fields['assigned_to'].queryset = User.objects.filter(is_active=True).order_by(
            'first_name', 'username'
        )
        self.fields['assigned_to'].required = True
        self.fields['assigned_to'].empty_label = 'اختر الموظف...'
        self.fields['assigned_to'].label_from_instance = (
            lambda user: user.display_name or user.get_full_name() or user.username
        )
        self.fields['title'].required = True
        self.fields['description'].required = False

        branch_names = Branch.active_names()
        choices = [('', 'اختر الفرع...')] + [(n, n) for n in branch_names]
        current = ''
        if self.is_bound:
            current = (self.data.get('branch') or '').strip()
        elif getattr(self.instance, 'pk', None):
            current = (self.instance.branch or '').strip()
        if current and current not in dict(choices):
            choices.append((current, current))
        self.fields['branch'].choices = choices
        self.fields['branch'].required = True
        if not branch_names:
            self.fields['branch'].help_text = 'لا فروع نشطة — أضفها من شاشة الفروع أولاً.'
        elif not self.is_bound and not getattr(self.instance, 'pk', None):
            default = Branch.default_name()
            if default:
                self.fields['branch'].initial = default
            default_due = timezone.localtime() + timedelta(days=3)
            self.fields['due_at'].initial = default_due.strftime('%Y-%m-%dT%H:%M')

        self.fields['due_at'].required = False
        self.fields['due_at'].help_text = 'افتراضي بعد 3 أيام — يمكن تركه فارغاً.'
        self.fields['description'].label = 'الوصف'
        self.fields['priority'].label = 'الأولوية'
        self.fields['assigned_to'].label = 'تعيين للموظف'
        self.fields['branch'].label = 'موقع الفرع'
        self.fields['due_at'].label = 'الموعد'

        # Keep legacy free-text titles selectable when editing
        current = None
        if self.is_bound:
            current = (self.data.get('title') or '').strip()
        elif getattr(self.instance, 'pk', None):
            current = (self.instance.title or '').strip()
        if current and current not in dict(self.TITLE_CHOICES):
            self.fields['title'].choices = list(self.TITLE_CHOICES) + [(current, current)]

    def clean_due_at(self):
        value = self.cleaned_data.get('due_at')
        if value is None:
            return value
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value
