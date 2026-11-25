"""Return, partial return and lost-item services."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..models import (
    LoanEvent,
    LoanEventType,
    LoanItem,
    LoanStatus,
    ReturnCondition,
)
from ..permissions import can_handout
from .notifications import notify_item_lost, notify_loan_returned
from .setup import get_loan_location


def _as_quantity(value) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"quantity": _("Enter a valid quantity")}) from None
    if quantity <= 0:
        raise ValidationError({"quantity": _("Quantity must be greater than zero")})
    return quantity


def _return_status_code(item: LoanItem) -> int:
    from stock.status_codes import StockStatus

    return (
        item.status_custom_key_on_issue
        or item.status_on_issue
        or StockStatus.OK.value
    )


@transaction.atomic
def return_item(
    loan_item: LoanItem,
    actor,
    *,
    quantity=None,
    condition: str = ReturnCondition.GOOD,
    notes: str = "",
    location=None,
) -> LoanItem:
    """Return all or part of a loaned item to its original location."""
    if not can_handout(actor):
        raise PermissionDenied("You do not have permission to receive returns")

    item = (
        LoanItem.objects.select_for_update()
        .select_related("loan", "stock_item", "original_location", "part")
        .get(pk=loan_item.pk)
    )
    if item.lost:
        raise ValidationError(_("This item has already been marked lost"))
    if not item.is_open:
        raise ValidationError(_("This item has already been returned"))

    clean_notes = (notes or "").strip()
    quantity = _as_quantity(quantity if quantity is not None else item.remaining_quantity)
    if quantity > item.remaining_quantity:
        raise ValidationError(
            {"quantity": _("Only %(remaining)s remain outstanding") % {"remaining": item.remaining_quantity}}
        )

    destination = location or item.original_location
    if destination is None and item.original_stock_item is not None:
        destination = item.original_stock_item.location
    loan_location = get_loan_location()
    if destination is None and loan_location is not None:
        destination = loan_location.parent
    if destination is None:
        raise ValidationError(
            _("The original stock location is missing. Select a return location.")
        )

    if loan_location is not None and destination.pk == loan_location.pk:
        raise ValidationError(_("Items cannot be returned to the loan location"))

    stock_item = item.stock_item
    if stock_item is None:
        raise ValidationError(
            _("The stock item is missing from this loan line. Contact an administrator.")
        )
    if stock_item.serialized and quantity != item.remaining_quantity:
        raise ValidationError(
            _("Serialized stock items must be returned in full")
        )
    stock_item._loan_plugin_allow = True
    note = f"Returned ({item.loan.reference})"
    if clean_notes:
        note = f"{note}: {clean_notes}"

    # merge=False keeps the returned stock item intact.  This preserves the
    # LoanItem -> StockItem link, which is important for audit history.
    stock_item.return_to_stock(
        destination,
        actor,
        quantity=quantity,
        merge=False,
        status=_return_status_code(item),
        notes=note,
    )

    item.returned_quantity += quantity
    item.condition_on_return = condition or ReturnCondition.GOOD
    if clean_notes:
        item.return_notes = (
            f"{item.return_notes}\n{clean_notes}".strip()
            if item.return_notes
            else clean_notes
        )

    fully_returned = item.remaining_quantity <= 0
    if fully_returned:
        item.returned_at = timezone.now()
    item.save(
        update_fields=[
            "returned_quantity",
            "condition_on_return",
            "return_notes",
            "returned_at",
            "updated",
        ]
    )

    event_type = LoanEventType.RETURNED if fully_returned else LoanEventType.PARTIALLY_RETURNED
    LoanEvent.record(
        loan=item.loan,
        event_type=event_type,
        actor=actor,
        notes=clean_notes,
        stock_item=item.stock_item_id,
        quantity=str(quantity),
        condition=condition,
    )

    item.loan.refresh_status()
    if item.loan.status == LoanStatus.RETURNED:
        notify_loan_returned(item.loan)
    return item


@transaction.atomic
def return_loan(loan, actor, lines: list[dict]) -> list[LoanItem]:
    """Return one or more lines on a loan."""
    results = []
    for line in lines:
        item_id = line.get("item_id") or line.get("loan_item_id") or line.get("id")
        if not item_id:
            continue
        item = LoanItem.objects.get(pk=item_id, loan=loan)
        location = line.get("location")
        if location and not hasattr(location, "pk"):
            from stock.models import StockLocation

            location = StockLocation.objects.filter(pk=location).first()
        results.append(
            return_item(
                item,
                actor,
                quantity=line.get("quantity"),
                condition=line.get("condition", ReturnCondition.GOOD),
                notes=line.get("notes", ""),
                location=location,
            )
        )
    if not results:
        raise ValidationError(_("No items were selected for return"))
    return results


@transaction.atomic
def mark_lost(loan_item: LoanItem, actor, notes: str = "") -> LoanItem:
    """Mark an item as lost and close its loan line."""
    if not can_handout(actor):
        raise PermissionDenied("You do not have permission to mark items lost")

    item = (
        LoanItem.objects.select_for_update()
        .select_related("loan", "stock_item", "part")
        .get(pk=loan_item.pk)
    )
    if not item.is_open:
        raise ValidationError(_("Only open loan items can be marked lost"))

    clean_notes = (notes or "").strip()
    from stock.status_codes import StockStatus

    stock_item = item.stock_item
    if stock_item is None:
        raise ValidationError(
            _("The stock item is missing from this loan line. Contact an administrator.")
        )
    stock_item._loan_plugin_allow = True
    stock_item.set_status(StockStatus.LOST.value)
    stock_item.save()

    item.lost = True
    item.lost_at = timezone.now()
    item.returned_quantity = item.quantity
    item.returned_at = timezone.now()
    if clean_notes:
        item.return_notes = (
            f"{item.return_notes}\n{clean_notes}".strip()
            if item.return_notes
            else clean_notes
        )
    item.save(
        update_fields=[
            "lost",
            "lost_at",
            "returned_quantity",
            "returned_at",
            "return_notes",
            "updated",
        ]
    )

    LoanEvent.record(
        loan=item.loan,
        event_type=LoanEventType.LOST,
        actor=actor,
        notes=clean_notes,
        stock_item=item.stock_item_id,
        quantity=str(item.quantity),
    )
    item.loan.refresh_status()
    notify_item_lost(item)
    return item


@transaction.atomic
def renew_loan(loan, actor, new_due_at, notes: str = ""):
    """Extend a loan's due date."""
    from ..config import get_setting

    if not can_handout(actor):
        raise PermissionDenied("You do not have permission to renew loans")
    if not get_setting("ALLOW_RENEWAL", True):
        raise ValidationError(_("Renewals are disabled"))
    if loan.renewals >= int(get_setting("MAX_RENEWALS", 1) or 1):
        raise ValidationError(_("This loan has reached its renewal limit"))

    from ..models import Loan

    loan = Loan.objects.select_for_update().get(pk=loan.pk)
    if not loan.is_open:
        raise ValidationError(_("Only open loans can be renewed"))

    if isinstance(new_due_at, datetime):
        due = new_due_at
    else:
        due = timezone.make_aware(datetime.combine(new_due_at, time(23, 59, 59)))
    if due <= loan.due_at:
        raise ValidationError(_("The new due date must be later than the current due date"))
    if due <= timezone.now():
        raise ValidationError(_("The new due date must be in the future"))

    loan.due_at = due
    loan.renewals += 1
    loan.save(update_fields=["due_at", "renewals", "updated"])
    loan.refresh_status()

    LoanEvent.record(
        loan=loan,
        event_type=LoanEventType.RENEWED,
        actor=actor,
        notes=(notes or "").strip(),
        due_at=due.isoformat(),
    )
    from .notifications import notify_loan_renewed

    notify_loan_renewed(loan)
    return loan
