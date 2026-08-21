from django.contrib import admin

from .models import (
    Branch,
    CatalogItem,
    DailyOrder,
    DailySupplyDistribution,
    DistributionVariance,
    EvolutionConfig,
    ReturnRequest,
    SupplyOrder,
    Supplier,
    Task,
    TaskResponsePhoto,
    WhatsAppRoleContact,
)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'is_default', 'sort_order', 'updated_at')
    list_editable = ('is_active', 'is_default', 'sort_order')
    search_fields = ('name',)
    list_filter = ('is_active', 'is_default')


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'is_active', 'sort_order', 'updated_at')
    list_editable = ('phone', 'is_active', 'sort_order')
    search_fields = ('name', 'phone')
    list_filter = ('is_active',)


@admin.register(DailyOrder)
class DailyOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number', 'batch_number', 'order_date', 'item_name', 'item_number',
        'quantity', 'unit_price', 'representative', 'branch', 'supplier',
        'status', 'created_at',
    )
    list_filter = ('order_date', 'status', 'branch', 'supplier')
    search_fields = ('order_number', 'batch_number', 'item_name', 'item_number', 'branch', 'supplier')
    readonly_fields = ('order_number',)
    raw_id_fields = ('representative', 'created_by', 'reviewed_by')


@admin.register(CatalogItem)
class CatalogItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'item_number', 'unit', 'package', 'updated_at')
    search_fields = ('name', 'item_number', 'unit', 'package')


@admin.register(SupplyOrder)
class SupplyOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number', 'batch_number', 'representative', 'branch', 'supplier',
        'item_name', 'item_number', 'quantity', 'status', 'created_at',
    )
    list_filter = ('status', 'branch', 'supplier')
    search_fields = ('order_number', 'batch_number', 'item_name', 'item_number', 'branch', 'supplier')


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
    list_display = ('title', 'branch', 'priority', 'status', 'assigned_to', 'due_at')
    list_filter = ('status', 'priority')
    search_fields = ('title', 'branch', 'visit_details', 'public_token', 'response_text')
    readonly_fields = ('public_token', 'completed_at', 'response_submitted_at', 'reviewed_at')


@admin.register(TaskResponsePhoto)
class TaskResponsePhotoAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'uploaded_at')
    raw_id_fields = ('task',)


@admin.register(DailySupplyDistribution)
class DailySupplyDistributionAdmin(admin.ModelAdmin):
    list_display = (
        'distribution_date', 'item_name', 'item_number', 'branch',
        'quantity', 'created_by', 'created_at',
    )
    list_filter = ('distribution_date', 'branch')
    search_fields = ('item_name', 'item_number', 'branch', 'notes')
    raw_id_fields = ('created_by',)


@admin.register(DistributionVariance)
class DistributionVarianceAdmin(admin.ModelAdmin):
    list_display = (
        'record_date', 'variance_type', 'item_name', 'branch', 'quantity',
        'supplier', 'status', 'authorized_by', 'created_at',
    )
    list_filter = ('variance_type', 'status', 'record_date', 'branch')
    search_fields = ('item_name', 'item_number', 'branch', 'supplier', 'notes')
    raw_id_fields = ('created_by', 'authorized_by')


@admin.register(EvolutionConfig)
class EvolutionConfigAdmin(admin.ModelAdmin):
    list_display = ('instance_name', 'server_url', 'notify_enabled', 'updated_at')


@admin.register(WhatsAppRoleContact)
class WhatsAppRoleContactAdmin(admin.ModelAdmin):
    list_display = ('role', 'phone', 'updated_at')
    list_editable = ('phone',)
