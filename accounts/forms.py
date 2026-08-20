from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()

FIELD_CLASS = (
    'w-full bg-white border border-[#bfdbfe] rounded-lg py-2.5 px-3 '
    'focus:border-[#1d4ed8] focus:ring-1 focus:ring-[#1d4ed8] '
    'text-[15px] font-semibold text-black transition-colors'
)

SELECT_CLASS = FIELD_CLASS + ' app-select'


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(
        label='كلمة المرور',
        widget=forms.PasswordInput(attrs={'class': FIELD_CLASS, 'placeholder': '••••••••'}),
        min_length=6,
    )
    password_confirm = forms.CharField(
        label='تأكيد كلمة المرور',
        widget=forms.PasswordInput(attrs={'class': FIELD_CLASS, 'placeholder': '••••••••'}),
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'role', 'whatsapp', 'password']
        widgets = {
            'username': forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'اسم المستخدم للدخول'}),
            'first_name': forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'الاسم الأول'}),
            'last_name': forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'اسم العائلة'}),
            'role': forms.Select(attrs={'class': SELECT_CLASS}),
            'whatsapp': forms.TextInput(attrs={
                'class': FIELD_CLASS,
                'placeholder': '9665xxxxxxxx',
                'dir': 'ltr',
            }),
        }
        labels = {
            'username': 'اسم المستخدم',
            'first_name': 'الاسم الأول',
            'last_name': 'اسم العائلة',
            'role': 'الدور',
            'whatsapp': 'واتساب',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = User.Role.choices

    def clean_whatsapp(self):
        value = (self.cleaned_data.get('whatsapp') or '').strip()
        digits = ''.join(ch for ch in value if ch.isdigit())
        if value.startswith('+'):
            digits = ''.join(ch for ch in value[1:] if ch.isdigit())
        if digits.startswith('00'):
            digits = digits[2:]
        return digits

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        confirm = cleaned.get('password_confirm')
        if password and confirm and password != confirm:
            self.add_error('password_confirm', 'كلمتا المرور غير متطابقتين.')
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if user.role in User.MANAGEMENT_ROLES:
            user.is_staff = True
        else:
            user.is_staff = False
        if commit:
            user.save()
        return user


class UserUpdateForm(forms.ModelForm):
    new_password = forms.CharField(
        label='كلمة مرور جديدة (اختياري)',
        required=False,
        widget=forms.PasswordInput(attrs={'class': FIELD_CLASS, 'placeholder': 'اتركها فارغة إن لم تتغير'}),
        min_length=6,
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'role', 'whatsapp', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={'class': FIELD_CLASS}),
            'first_name': forms.TextInput(attrs={'class': FIELD_CLASS}),
            'last_name': forms.TextInput(attrs={'class': FIELD_CLASS}),
            'role': forms.Select(attrs={'class': SELECT_CLASS}),
            'whatsapp': forms.TextInput(attrs={
                'class': FIELD_CLASS,
                'placeholder': '9665xxxxxxxx',
                'dir': 'ltr',
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'rounded border-outline-variant text-primary focus:ring-primary',
            }),
        }
        labels = {
            'username': 'اسم المستخدم',
            'first_name': 'الاسم الأول',
            'last_name': 'اسم العائلة',
            'role': 'الدور',
            'whatsapp': 'واتساب',
            'is_active': 'الحساب نشط',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = User.Role.choices

    def clean_whatsapp(self):
        value = (self.cleaned_data.get('whatsapp') or '').strip()
        digits = ''.join(ch for ch in value if ch.isdigit())
        if value.startswith('+'):
            digits = ''.join(ch for ch in value[1:] if ch.isdigit())
        if digits.startswith('00'):
            digits = digits[2:]
        return digits

    def save(self, commit=True):
        user = super().save(commit=False)
        new_password = self.cleaned_data.get('new_password')
        if new_password:
            user.set_password(new_password)
        user.is_staff = user.role in User.MANAGEMENT_ROLES
        if commit:
            user.save()
        return user
