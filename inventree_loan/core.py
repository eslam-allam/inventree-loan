"""InvenTree Loan Manager plugin entry point."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from plugin import InvenTreePlugin
from plugin.mixins import (
    AppMixin,
    NavigationMixin,
    ScheduleMixin,
    SettingsMixin,
    UrlsMixin,
    UserInterfaceMixin,
    ValidationMixin,
)

from . import PLUGIN_VERSION


class InvenTreeLoanPlugin(
    AppMixin,
    UrlsMixin,
    SettingsMixin,
    ScheduleMixin,
    NavigationMixin,
    UserInterfaceMixin,
    ValidationMixin,
    InvenTreePlugin,
):
    """Loan and return management for InvenTree."""

    NAME = "InvenTreeLoan"
    SLUG = "loan"
    TITLE = _("InvenTree Loan Manager")
    DESCRIPTION = _(
        "Loan and return management with user requests, staff approvals, "
        "barcode/QR workflows and a complete audit history."
    )
    VERSION = PLUGIN_VERSION
    AUTHOR = "InvenTree Loan Contributors"
    WEBSITE = "https://github.com/inventree/inventree-loan"
    LICENSE = "MIT"

    MIN_VERSION = "1.5.0"
    MAX_VERSION = "1.5.99"

    # Native React / Mantine admin UI, rendered inside the standard InvenTree
    # plugin administration page.
    ADMIN_SOURCE = "admin.js:renderPluginSettings"

    NAVIGATION = [
        {
            "name": _("Loans"),
            "link": "plugin:loan:dashboard",
            "icon": "ti ti-box",
        }
    ]
    NAVIGATION_TAB_NAME = _("Loans")
    NAVIGATION_TAB_ICON = "ti ti-box"

    SCHEDULED_TASKS = {
        "due_reminders": {
            "func": "send_due_reminders",
            "schedule": "I",
            "hours": 24,
        }
    }

    SETTINGS = {
        "LOAN_LOCATION": {
            "name": _("On Loan location"),
            "description": _(
                "Stock location used while items are on loan. Items are moved here "
                "and receive the On Loan status."
            ),
            "model": "stock.stocklocation",
            "model_filters": {"structural": False},
            "required": False,
        },
        "ON_LOAN_STATUS_NAME": {
            "name": _("On Loan status name"),
            "description": _(
                "Internal name for the custom stock status. Leave as ON_LOAN unless "
                "you already use a different custom status."
            ),
            "default": "ON_LOAN",
        },
        "LOANABLE_CATEGORY": {
            "name": _("Loanable part category"),
            "description": _(
                "If set, only parts in this category (or its children) can be requested."
            ),
            "model": "part.partcategory",
            "required": False,
        },
        "REQUEST_GROUP": {
            "name": _("Request group"),
            "description": _(
                "If set, only members of this group can submit loan requests."
            ),
            "model": "auth.group",
            "required": False,
        },
        "LOAN_DURATION_DAYS": {
            "name": _("Default loan duration (days)"),
            "description": _("Default number of days between pickup and return."),
            "default": 14,
            "validator": int,
        },
        "DUE_SOON_DAYS": {
            "name": _("Due soon reminder (days)"),
            "description": _("Send a reminder this many days before the due date."),
            "default": 2,
            "validator": int,
        },
        "OVERDUE_REMINDER_DAYS": {
            "name": _("Overdue reminder interval (days)"),
            "description": _("How often to repeat overdue reminders."),
            "default": 1,
            "validator": int,
        },
        "SEND_DUE_REMINDERS": {
            "name": _("Send due reminders"),
            "description": _("Enable the scheduled due-soon and overdue notifications."),
            "default": True,
            "validator": bool,
        },
        "MAX_ACTIVE_LOANS_PER_USER": {
            "name": _("Maximum active loans per user"),
            "description": _("Set to 0 for no limit."),
            "default": 0,
            "validator": int,
        },
        "MAX_ITEMS_PER_REQUEST": {
            "name": _("Maximum items per request"),
            "description": _("Maximum number of lines in a single request."),
            "default": 25,
            "validator": int,
        },
        "REQUIRE_APPROVAL": {
            "name": _("Require approval"),
            "description": _("Requests must be approved before items can be handed out."),
            "default": True,
            "validator": bool,
        },
        "ALLOW_DIRECT_CHECKOUT": {
            "name": _("Allow walk-in checkout"),
            "description": _("Loan desk staff can create a loan without a prior request."),
            "default": True,
            "validator": bool,
        },
        "ALLOW_RENEWAL": {
            "name": _("Allow renewals"),
            "description": _("Loan desk staff can extend a loan's due date."),
            "default": True,
            "validator": bool,
        },
        "MAX_RENEWALS": {
            "name": _("Maximum renewals"),
            "description": _("Maximum number of renewals per loan."),
            "default": 1,
            "validator": int,
        },
        "REQUIRE_RESPONSIBILITY_ACK": {
            "name": _("Require responsibility acknowledgement"),
            "description": _("Requesters must accept the loan responsibility statement."),
            "default": True,
            "validator": bool,
        },
        "REQUIRE_STOCK_PERMISSION": {
            "name": _("Require core stock permission"),
            "description": _(
                "Also require InvenTree stock change permission for handout and return "
                "actions. Disabled by default because loan staff roles already govern "
                "the plugin workflows."
            ),
            "default": False,
            "validator": bool,
        },
        "LOCK_STOCK_ITEM": {
            "name": _("Lock loaned stock items"),
            "description": _(
                "Prevent direct InvenTree edits, moves, quantity changes and deletion "
                "while an item is on loan."
            ),
            "default": True,
            "validator": bool,
        },
        "SHOW_BORROWER_DETAILS_TO_MANAGERS_ONLY": {
            "name": _("Hide borrower details from requesters"),
            "description": _("Only loan staff see borrower details for loaned items."),
            "default": True,
            "validator": bool,
        },
        "ENABLE_EMAIL": {
            "name": _("Enable email notifications"),
            "description": _("Send email in addition to in-app notifications."),
            "default": False,
            "validator": bool,
        },
        "EMAIL_FROM": {
            "name": _("Email from address"),
            "description": _("Leave blank to use Django's DEFAULT_FROM_EMAIL."),
            "default": "",
        },
        "LOAN_QR_PREFIX": {
            "name": _("Loan QR prefix"),
            "description": _("Optional text prefix accepted before the loan QR token."),
            "default": "LOAN:",
        },
        "CATALOG_PAGE_SIZE": {
            "name": _("Catalog page size"),
            "description": _("Number of parts returned by a catalog search."),
            "default": 20,
            "validator": int,
        },
    }

    def setup_urls(self):
        """Return the plugin URL patterns."""
        from .urls import urlpatterns

        return urlpatterns

    def get_ui_navigation_items(self, request, context, **kwargs):
        """Add a Loans tab which opens the native plugin administration page."""
        from .config import get_admin_console_url

        return [
            {
                "key": "loan-manager",
                "title": str(_("Loans")),
                "icon": "ti:box:outline",
                "options": {"url": get_admin_console_url()},
            }
        ]

    def get_ui_dashboard_items(self, request, context, **kwargs):
        """Add a Loan Manager / Request a loan card to the standard dashboard."""
        if not request.user.is_authenticated:
            return []

        from .config import get_admin_console_url
        from .permissions import can_view_all

        try:
            request_url = reverse("plugin:loan:request_new")
        except Exception:  # pragma: no cover
            return []

        return [
            {
                "key": "loan-entry",
                "title": str(_("Loans")),
                "description": str(
                    _("Request a loan or open the loan management console.")
                ),
                "icon": "ti:box:outline",
                "source": self.plugin_static_file(
                    "admin.js:renderLoanDashboardItem"
                ),
                "context": {
                    "is_manager": can_view_all(request.user),
                    "request_url": request_url,
                    "admin_url": get_admin_console_url(),
                },
                "options": {"width": 3, "height": 2},
            }
        ]

    def get_admin_context(self) -> dict:
        """Context passed to the native plugin administration UI."""
        from .services.setup import (
            get_loan_location,
            get_on_loan_status,
            is_configured,
        )

        location = get_loan_location()
        status = get_on_loan_status()
        return {
            "setup_configured": is_configured(),
            "loan_location": getattr(location, "pathstring", ""),
            "loan_location_id": getattr(location, "pk", None),
            "on_loan_status": getattr(status, "label", ""),
            "on_loan_status_key": getattr(status, "key", None),
            "request_url": reverse("plugin:loan:request_new"),
        }

    def send_due_reminders(self):
        """Scheduled task entry point."""
        from .tasks import send_due_reminders

        send_due_reminders()

    def validate_model_instance(self, instance, deltas=None) -> bool | None:
        """Protect loaned stock items from direct core edits."""
        label = instance._meta.label_lower
        if label != "stock.stockitem" and label not in {
            "order.salesorderallocation",
            "build.builditem",
            "order.transferorderallocation",
        }:
            return None

        try:
            lock_enabled = self.get_setting("LOCK_STOCK_ITEM", cache=True, backup_value=True)
        except Exception:  # pragma: no cover - during migrations/app loading
            lock_enabled = True
        if not lock_enabled:
            return None

        if label == "stock.stockitem":
            if getattr(instance, "_loan_plugin_allow", False):
                return None
            if instance.pk is None:
                return None
            if not self._stock_item_on_loan(instance):
                return None

            blocked = {
                "location",
                "location_id",
                "status",
                "status_custom_key",
                "quantity",
                "part",
                "part_id",
                "customer",
                "customer_id",
                "sales_order",
                "sales_order_id",
                "belongs_to",
                "belongs_to_id",
                "consumed_by",
                "consumed_by_id",
                "build",
                "build_id",
                "parent",
                "parent_id",
                "serial",
                "batch",
            }
            if deltas and blocked.intersection(deltas.keys()):
                raise ValidationError(
                    _(
                        "This stock item is on loan and is locked by the Loan Manager. "
                        "Use the loan return workflow to change its location, status or quantity."
                    )
                )

        # Guard allocation records if a core operation bypasses the stock filters.
        if label in {
            "order.salesorderallocation",
            "build.builditem",
            "order.transferorderallocation",
        }:
            stock_item = getattr(instance, "stock_item", None) or getattr(instance, "item", None)
            if stock_item is not None and self._stock_item_on_loan(stock_item):
                raise ValidationError(
                    _("This stock item is on loan and cannot be allocated.")
                )

        return None

    def validate_model_deletion(self, instance) -> None:
        """Prevent deletion of a stock item while it is on loan."""
        if instance._meta.label_lower != "stock.stockitem":
            return
        if self._stock_item_on_loan(instance):
            raise ValidationError(
                _("This stock item is on loan and cannot be deleted.")
            )

    @staticmethod
    def _stock_item_on_loan(stock_item) -> bool:
        """Return True if the stock item has an open loan line."""
        try:
            from .models import LoanItem

            return LoanItem.objects.filter(
                stock_item=stock_item, returned_at__isnull=True, lost=False
            ).exists()
        except Exception:  # pragma: no cover - during migrations/app loading
            return False
