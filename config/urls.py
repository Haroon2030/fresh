from django.contrib import admin
from django.urls import include, path

from ops.media_views import media_proxy

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('', include(('ops.urls', 'ops'))),
    path('media/<path:path>', media_proxy, name='media_proxy'),
]
