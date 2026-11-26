"""Django admin registrations for loan records."""

from django.contrib import admin

from .models import (
    Loan,
    LoanEvent,
    LoanItem,
    LoanPickup,
    LoanRequest,
    LoanRequestCustomField,
    LoanRequestLine,
    LoanStaff,
)


def _register(model, admin_class):
    """Register a model once, tolerating AppMixin admin reloads."""
    if not admin.site.is_registered(model):
        admin.site.register(model, admin_class)


class LoanRequestLineInline(admin.TabularInline):
    model = LoanRequestLine
    extra = 0
    raw_id_fields = ("part", "stock_item")


class LoanRequestAdmin(admin.ModelAdmin):
    list_display = ("reference", "requester", "status", "needed_by", "return_by", "created")
    list_filter = ("status",)
    search_fields = ("reference", "requester__username", "purpose")
    raw_id_fields = ("requester", "decided_by")
    readonly_fields = ("reference", "created", "updated")
    inlines = [LoanRequestLineInline]


class LoanItemInline(admin.TabularInline):
    model = LoanItem
    extra = 0
    raw_id_fields = ("part", "stock_item", "original_stock_item", "original_location")
    readonly_fields = (
        "status_on_issue",
        "status_custom_key_on_issue",
        "returned_quantity",
        "returned_at",
    )


class LoanAdmin(admin.ModelAdmin):
    list_display = ("reference", "borrower", "status", "issued_at", "due_at", "returned_at")
    list_filter = ("status",)
    search_fields = ("reference", "borrower__username", "borrower__email")
    raw_id_fields = ("request", "borrower", "issued_by", "checkout_location")
    readonly_fields = ("reference", "token", "created", "updated")
    inlines = [LoanItemInline]


class LoanItemAdmin(admin.ModelAdmin):
    list_display = ("loan", "part", "quantity", "returned_quantity", "lost", "returned_at")
    list_filter = ("lost",)
    search_fields = ("loan__reference", "part__name", "part__IPN", "stock_item__serial")
    raw_id_fields = ("loan", "part", "stock_item", "original_stock_item", "original_location")


class LoanEventAdmin(admin.ModelAdmin):
    list_display = ("created", "event_type", "actor_name", "request", "loan")
    list_filter = ("event_type",)
    search_fields = ("actor_name", "notes", "loan__reference", "request__reference")
    raw_id_fields = ("request", "loan", "actor")
    readonly_fields = (
        "request",
        "loan",
        "event_type",
        "actor",
        "actor_name",
        "notes",
        "metadata",
        "created",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class LoanRequestCustomFieldAdmin(admin.ModelAdmin):
    list_display = ("label", "key", "field_type", "required", "active", "sort_order")
    list_filter = ("field_type", "required", "active")
    search_fields = ("label", "key")
    readonly_fields = ("created", "updated")


class LoanPickupAdmin(admin.ModelAdmin):
    list_display = ("reference", "name", "request", "status", "ready_at", "collected_at")
    list_filter = ("status",)
    search_fields = ("reference", "name", "request__reference")
    raw_id_fields = ("request", "created_by")
    readonly_fields = ("reference", "token", "created", "updated")


class LoanStaffAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "active", "created_by", "created")
    list_filter = ("role", "active")
    search_fields = ("user__username", "user__email")
    raw_id_fields = ("user", "created_by")


_register(LoanRequest, LoanRequestAdmin)
_register(Loan, LoanAdmin)
_register(LoanItem, LoanItemAdmin)
_register(LoanEvent, LoanEventAdmin)
_register(LoanRequestCustomField, LoanRequestCustomFieldAdmin)
_register(LoanPickup, LoanPickupAdmin)
_register(LoanStaff, LoanStaffAdmin)
