from django.contrib import admin

from .models import CatalogItem, ReturnRequest, SupplyOrder, Task


@admin.register(CatalogItem)
class CatalogItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'item_number', 'unit', 'package', 'updated_at')
    search_fields = ('name', 'item_number', 'unit', 'package')


@admin.register(SupplyOrder)
class SupplyOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number', 'representative', 'item_name', 'item_number',
        'quantity', 'status', 'created_at',
    )
    list_filter = ('status',)
    search_fields = ('order_number', 'item_name', 'item_number')


@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    list_display = (
        'return_number', 'representative', 'item_name', 'return_type',
        'rep_decision', 'quantity', 'status', 'created_at',
    )
    list_filter = ('status', 'return_type', 'rep_decision')
    search_fields = ('return_number', 'item_name', 'item_number')


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'priority', 'status', 'assigned_to', 'due_at')
    list_filter = ('status', 'priority')
    search_fields = ('title',)
