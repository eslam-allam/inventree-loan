"""Loan checkout service: turn an approved request into an issued loan."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..config import get_setting
from ..models import (
    Loan,
    LoanEvent,
    LoanEventType,
    LoanItem,
    LoanRequest,
    LoanRequestAllocation,
    LoanRequestLine,
    LoanRequestStatus,
    LoanStatus,
)
from ..permissions import can_handout
from ..utils import clean_signature, local_today
from .notifications import notify_loan_issued
from .requests import (
    _check_active_loan_limit,
    _validate_lines,
    available_stock_queryset,
    stock_item_available_quantity,
)
from .setup import get_loan_location, get_on_loan_status_key


def _resolve_due_at(due_at=None, default_date=None):
    if due_at is None:
        if default_date is not None:
            due = timezone.make_aware(datetime.combine(default_date, time(23, 59, 59)))
            if due > timezone.now():
                return due
        days = int(get_setting("LOAN_DURATION_DAYS", 14) or 14)
        return timezone.now() + timedelta(days=max(days, 1))
    if isinstance(due_at, datetime):
        return due_at
    # A date object: due at the end of that day
    return timezone.make_aware(datetime.combine(due_at, time(23, 59, 59)))


def _issue_stock_item(
    *,
    loan: Loan,
    stock_item,
    quantity: Decimal,
    actor,
    loan_location,
    status_key: int,
) -> LoanItem:
    """Move or split a stock item into the loan location and record it."""
    original_status = stock_item.status
    original_custom_status = stock_item.get_custom_status()
    original_location = stock_item.location
    note = f"Loaned to {loan.borrower_display} ({loan.reference})"

    if quantity < stock_item.quantity:
        moved = stock_item.splitStock(
            quantity, loan_location, actor, notes=note
        )
        if moved is None:
            raise ValidationError(_("Unable to split the stock item for this loan"))
    else:
        moved = stock_item
        if not moved.move(loan_location, note, actor):
            raise ValidationError(_("Unable to move the stock item to the loan location"))

    moved._loan_plugin_allow = True
    moved.set_status(status_key)
    moved.save()

    return LoanItem.objects.create(
        loan=loan,
        part=moved.part,
        stock_item=moved,
        stock_item_label=str(moved)[:255],
        stock_item_serial=moved.serial or "",
        original_stock_item=moved.parent,
        original_location=original_location,
        quantity=quantity,
        status_on_issue=original_status,
        status_custom_key_on_issue=original_custom_status,
    )


def _allocate_line(
    *,
    loan: Loan,
    line: LoanRequestLine,
    actor,
    loan_location,
    status_key: int,
) -> list[LoanItem]:
    """Allocate one request line to one or more physical stock items."""
    from stock.models import StockItem

    wanted = line.quantity
    allocations: list[tuple] = []

    planned = list(
        LoanRequestAllocation.objects.filter(line=line).select_related("stock_item")
    )
    if planned:
        planned_total = sum(
            (allocation.quantity for allocation in planned), Decimal(0)
        )
        if planned_total != wanted:
            raise ValidationError(
                _(
                    "The allocated quantity for %(part)s does not match the requested quantity"
                )
                % {"part": line.part}
            )
        for allocation in planned:
            stock_item = StockItem.objects.select_for_update().get(
                pk=allocation.stock_item_id
            )
            available = stock_item_available_quantity(stock_item)
            if available < allocation.quantity:
                raise ValidationError(
                    _("Stock item %(item)s is no longer available in the allocated quantity")
                    % {"item": stock_item.pk}
                )
            allocations.append((stock_item, allocation.quantity))
    elif line.stock_item_id:
        stock_item = StockItem.objects.select_for_update().get(pk=line.stock_item_id)
        available = stock_item_available_quantity(stock_item)
        if available < wanted:
            raise ValidationError(
                _("Stock item %(item)s is no longer available in the requested quantity")
                % {"item": stock_item.pk}
            )
        allocations.append((stock_item, wanted))
    else:
        queryset = (
            available_stock_queryset(line.part)
            .select_for_update()
            .order_by("expiry_date", "updated", "pk")
        )
        remaining = wanted
        for stock_item in queryset:
            available = min(
                max(stock_item.unallocated_quantity(), Decimal(0)),
                stock_item.quantity,
            )
            if available <= 0:
                continue
            if stock_item.serialized:
                if remaining < 1:
                    break
                take = Decimal(1)
            else:
                take = min(remaining, available)
            allocations.append((stock_item, take))
            remaining -= take
            if remaining <= 0:
                break

        if remaining > 0:
            raise ValidationError(
                _("Insufficient stock for %(part)s: %(remaining)s more required")
                % {"part": line.part, "remaining": remaining}
            )

    items = []
    for stock_item, quantity in allocations:
        items.append(
            _issue_stock_item(
                loan=loan,
                stock_item=stock_item,
                quantity=quantity,
                actor=actor,
                loan_location=loan_location,
                status_key=status_key,
            )
        )
    return items


@transaction.atomic
def checkout_request(
    request: LoanRequest,
    actor,
    *,
    due_at=None,
    notes: str = "",
    allow_pending: bool = False,
    signature: str = "",
) -> Loan:
    """Issue the items for an approved request."""
    if not can_handout(actor):
        raise PermissionDenied("You do not have permission to issue loans")

    if get_setting("REQUIRE_STOCK_PERMISSION", False):
        from stock.models import StockItem
        from users.permissions import check_user_permission

        if not check_user_permission(actor, StockItem, "change"):
            raise PermissionDenied("You need stock change permission to issue loans")

    request = (
        LoanRequest.objects.select_for_update()
        .prefetch_related(
            "lines__part",
            "lines__stock_item",
            "lines__allocations__stock_item",
        )
        .get(pk=request.pk)
    )

    if Loan.objects.filter(request=request).exists():
        raise ValidationError(_("This request has already been issued"))

    require_approval = bool(get_setting("REQUIRE_APPROVAL", True))
    if request.status == LoanRequestStatus.PENDING:
        if require_approval and not allow_pending:
            raise ValidationError(_("This request has not been approved yet"))
    elif request.status != LoanRequestStatus.APPROVED:
        raise ValidationError(_("Only pending or approved requests can be issued"))

    if request.requester_id and not request.requester.is_active:
        raise ValidationError(_("The requester's account is inactive"))
    if not request.lines.exists():
        raise ValidationError(_("This request has no items"))

    if request.requester_id:
        _check_active_loan_limit(request.requester)

    signature = clean_signature(
        signature,
        required=bool(get_setting("REQUIRE_SIGNATURE_ON_HANDOUT", True)),
        field="signature",
    )

    loan_location = get_loan_location()
    if loan_location is None:
        raise ValidationError(
            _("The On Loan stock location is not configured. Open the loan setup page.")
        )
    if getattr(loan_location, "structural", False):
        raise ValidationError(
            _("The On Loan location must not be marked as structural.")
        )
    status_key = get_on_loan_status_key()

    loan = Loan.objects.create(
        request=request,
        borrower=request.requester,
        borrower_name=request.requester_display,
        borrower_email=request.requester_email_display,
        borrower_phone=request.requester_phone_display,
        issued_by=actor,
        due_at=_resolve_due_at(due_at, default_date=request.return_by),
        notes=(notes or "").strip() or request.notes,
        checkout_location=loan_location,
        signature_checkout=signature,
        signature_checkout_at=timezone.now() if signature else None,
        status=LoanStatus.ACTIVE,
    )

    from stock.models import StockItem

    lines = list(request.lines.all())
    planned: dict[int, Decimal] = {}
    for line in lines:
        allocations = list(line.allocations.all())
        if not allocations:
            continue
        allocated = sum(
            (allocation.quantity for allocation in allocations), Decimal(0)
        )
        if allocated != line.quantity:
            raise ValidationError(
                _(
                    "The allocated quantity for %(part)s does not match the requested quantity"
                )
                % {"part": line.part}
            )
        for allocation in allocations:
            planned[allocation.stock_item_id] = (
                planned.get(allocation.stock_item_id, Decimal(0))
                + allocation.quantity
            )

    issued_items = []
    for stock_item_id, quantity in planned.items():
        stock_item = StockItem.objects.select_for_update().get(pk=stock_item_id)
        available = stock_item_available_quantity(
            stock_item, exclude_request=request
        )
        if available < quantity:
            raise ValidationError(
                _("Stock item %(item)s is no longer available in the allocated quantity")
                % {"item": stock_item.pk}
            )
        issued_items.append(
            _issue_stock_item(
                loan=loan,
                stock_item=stock_item,
                quantity=quantity,
                actor=actor,
                loan_location=loan_location,
                status_key=status_key,
            )
        )

    for line in lines:
        if line.allocations.exists():
            continue
        issued_items.extend(
            _allocate_line(
                loan=loan,
                line=line,
                actor=actor,
                loan_location=loan_location,
                status_key=status_key,
            )
        )

    LoanRequestAllocation.objects.filter(line__request=request).delete()

    request.status = LoanRequestStatus.FULFILLED
    if request.decided_by_id is None:
        request.decided_by = actor
        request.decided_at = timezone.now()
    request.save(
        update_fields=["status", "decided_by", "decided_at", "updated"]
    )

    LoanEvent.record(
        request=request,
        loan=loan,
        event_type=LoanEventType.ISSUED,
        actor=actor,
        notes=(notes or "").strip(),
        items=len(issued_items),
        due_at=loan.due_at.isoformat(),
        signed=bool(signature),
    )
    notify_loan_issued(loan)
    return loan


@transaction.atomic
def checkout_direct(
    actor,
    borrower,
    lines: list[dict],
    *,
    due_at=None,
    notes: str = "",
    purpose: str = "Walk-in loan",
    signature: str = "",
) -> Loan:
    """Create and immediately issue a walk-in loan without a prior request."""
    if not can_handout(actor):
        raise PermissionDenied("You do not have permission to issue loans")
    if not borrower.is_active:
        raise ValidationError(_("The borrower's account is inactive"))

    signature = clean_signature(
        signature,
        required=bool(get_setting("REQUIRE_SIGNATURE_ON_HANDOUT", True)),
        field="signature",
    )

    cleaned = _validate_lines(lines)
    due = _resolve_due_at(due_at)
    request = LoanRequest.objects.create(
        requester=borrower,
        requester_name=borrower.get_full_name() or borrower.username,
        requester_email=borrower.email,
        status=LoanRequestStatus.APPROVED,
        purpose=(purpose or "").strip(),
        needed_by=local_today(),
        return_by=due.date(),
        notes=(notes or "").strip(),
        responsibility_ack=True,
        decided_by=actor,
        decided_at=timezone.now(),
    )
    for line in cleaned:
        LoanRequestLine.objects.create(
            request=request,
            part=line["part"],
            stock_item=line["stock_item"],
            quantity=line["quantity"],
            notes=line["notes"],
        )
    return checkout_request(
        request,
        actor,
        due_at=due,
        notes=notes,
        allow_pending=True,
        signature=signature,
    )
