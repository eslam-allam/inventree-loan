"""Signal guards for core allocation models that do not use plugin validation."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import OperationalError, ProgrammingError
from django.db.models.signals import pre_save
from django.utils.translation import gettext_lazy as _


def _blocked(stock_item_id) -> bool:
    """Return True if the stock item has an open loan line."""
    if not stock_item_id:
        return False
    try:
        from .models import LoanItem

        return LoanItem.objects.filter(
            stock_item_id=stock_item_id, returned_at__isnull=True, lost=False
        ).exists()
    except (OperationalError, ProgrammingError):  # pragma: no cover
        return False


def _guard(stock_item_id):
    if _blocked(stock_item_id):
        raise ValidationError(
            _("This stock item is on loan and cannot be allocated to another order.")
        )


def connect_signals():
    """Connect allocation guards. Safe to call more than once."""
    from django.apps import apps

    for model_name in ("SalesOrderAllocation", "TransferOrderAllocation"):
        try:
            model = apps.get_model("order", model_name)
        except LookupError:  # pragma: no cover
            continue
        pre_save.connect(
            _order_allocation_guard,
            sender=model,
            dispatch_uid=f"inventree_loan_guard_{model_name}",
            weak=False,
        )

    try:
        build_item = apps.get_model("build", "BuildItem")
    except LookupError:  # pragma: no cover
        build_item = None
    if build_item is not None:
        pre_save.connect(
            _build_item_guard,
            sender=build_item,
            dispatch_uid="inventree_loan_guard_builditem",
            weak=False,
        )


def _order_allocation_guard(sender, instance, **kwargs):
    """Block allocations against loaned stock items."""
    _guard(getattr(instance, "item_id", None))


def _build_item_guard(sender, instance, **kwargs):
    """Block build allocations against loaned stock items."""
    _guard(getattr(instance, "stock_item_id", None))
