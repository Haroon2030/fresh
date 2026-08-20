from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .forms import UserCreateForm, UserUpdateForm

User = get_user_model()


def manager_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_manager:
            messages.error(request, 'هذه العملية متاحة للمديرين فقط.')
            return redirect('ops:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


@require_http_methods(['GET', 'POST'])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('ops:dashboard')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if not user.is_active:
                error = 'هذا الحساب غير نشط. تواصل مع المدير.'
            else:
                login(request, user)
                next_url = request.GET.get('next') or 'ops:dashboard'
                return redirect(next_url)
        else:
            error = 'اسم المستخدم أو كلمة المرور غير صحيحة.'

    return render(request, 'accounts/login.html', {'error': error})


@require_POST
@login_required
def logout_view(request):
    logout(request)
    return redirect('accounts:login')


@manager_required
def users_list(request):
    qs = User.objects.all().order_by('role', 'first_name', 'username')
    q = request.GET.get('q', '').strip()
    role = request.GET.get('role', '')
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )
    if role in dict(User.Role.choices):
        qs = qs.filter(role=role)

    total = User.objects.count()
    managers = User.objects.filter(role__in=User.MANAGEMENT_ROLES).count()
    reps = User.objects.filter(role=User.Role.REPRESENTATIVE).count()
    inactive = User.objects.filter(is_active=False).count()

    paginator = Paginator(qs, 12)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'accounts/users.html', {
        'users': page,
        'page_obj': page,
        'create_form': UserCreateForm(),
        'q': q,
        'role_filter': role,
        'total_users': total,
        'managers_count': managers,
        'reps_count': reps,
        'inactive_count': inactive,
        'active_nav': 'users',
        'role_choices': User.Role.choices,
    })


@manager_required
@require_POST
def user_create(request):
    form = UserCreateForm(request.POST)
    if form.is_valid():
        user = form.save()
        messages.success(request, f'تم إنشاء المستخدم «{user.display_name}» بنجاح.')
    else:
        messages.error(request, 'تعذر إنشاء المستخدم. تحقق من البيانات.')
    return redirect('accounts:users')


@manager_required
@require_http_methods(['GET', 'POST'])
def user_edit(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = UserUpdateForm(request.POST, instance=user_obj)
        if form.is_valid():
            # Prevent manager from deactivating themselves
            if user_obj.pk == request.user.pk and not form.cleaned_data.get('is_active', True):
                messages.error(request, 'لا يمكنك إيقاف حسابك الحالي.')
                return redirect('accounts:user_edit', pk=pk)
            form.save()
            messages.success(request, 'تم تحديث بيانات المستخدم.')
            return redirect('accounts:users')
    else:
        form = UserUpdateForm(instance=user_obj)

    return render(request, 'accounts/user_edit.html', {
        'form': form,
        'edited_user': user_obj,
        'active_nav': 'users',
    })


@manager_required
@require_POST
def user_toggle_active(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    if user_obj.pk == request.user.pk:
        messages.error(request, 'لا يمكنك إيقاف حسابك الحالي.')
        return redirect('accounts:users')
    user_obj.is_active = not user_obj.is_active
    user_obj.save(update_fields=['is_active'])
    state = 'تفعيل' if user_obj.is_active else 'إيقاف'
    messages.success(request, f'تم {state} حساب «{user_obj.display_name}».')
    return redirect('accounts:users')
