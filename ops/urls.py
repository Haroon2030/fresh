from django.urls import path

from . import views

app_name = 'ops'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('supply/', views.supply_list, name='supply'),
    path('supply/create/', views.supply_create, name='supply_create'),
    path('supply/<int:pk>/', views.supply_detail, name='supply_detail'),
    path('supply/<int:pk>/complete/', views.supply_complete, name='supply_complete'),
    path('supply/<int:pk>/reject/', views.supply_reject, name='supply_reject'),
    path('returns/', views.returns_list, name='returns'),
    path('returns/create/', views.return_create, name='return_create'),
    path('returns/items/<int:pk>/update/', views.return_item_update, name='return_item_update'),
    path('returns/<int:pk>/authorize/', views.return_rep_authorize, name='return_authorize'),
    path('returns/<int:pk>/rep-reject/', views.return_rep_reject, name='return_rep_reject'),
    path('returns/<int:pk>/accept/', views.return_accept, name='return_accept'),
    path('returns/<int:pk>/reject/', views.return_reject, name='return_reject'),
    path('tasks/', views.tasks_board, name='tasks'),
    path('tasks/create/', views.task_create, name='task_create'),
    path('tasks/<int:pk>/move/', views.task_move, name='task_move'),
    path('tasks/p/<str:token>/', views.task_public, name='task_public'),
    path('items/', views.items_list, name='items'),
    path('items/create/', views.item_create, name='item_create'),
    path('items/<int:pk>/delete/', views.item_delete, name='item_delete'),
    path('items/import/', views.items_import_excel, name='items_import'),
    path('items/template/', views.items_template_download, name='items_template'),
    path('settings/', views.settings_view, name='settings'),
    path('whatsapp/', views.whatsapp_hub, name='whatsapp'),
    path('whatsapp/api/qr/', views.whatsapp_qr_api, name='whatsapp_qr'),
    path('whatsapp/api/status/', views.whatsapp_status_api, name='whatsapp_status'),
    path('whatsapp/api/logout/', views.whatsapp_logout_api, name='whatsapp_logout'),
    path('whatsapp/api/test/', views.whatsapp_test_api, name='whatsapp_test'),
]
