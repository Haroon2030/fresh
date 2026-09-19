from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from ops.media_views import media_proxy

urlpatterns = [
    path('admin/', admin.site.urls),
    # توافق مع الروابط القديمة/المحفوظة: /login/ → /accounts/login/
    path(
        'login/',
        RedirectView.as_view(pattern_name='accounts:login', query_string=True, permanent=False),
        name='login_alias',
    ),
    path('accounts/', include('accounts.urls')),
    path('', include(('ops.urls', 'ops'))),
    path('media/<path:path>', media_proxy, name='media_proxy'),
]
