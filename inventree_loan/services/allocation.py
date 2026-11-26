"""Stock allocation helpers for loan requests."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from ..models import LoanRequest, LoanRequestAllocation, LoanRequestStatus
from ..permissions import can_approve, can_handout
from .requests import available_stock_queryset, part_family_ids, stock_item_available_quantity


def _quantity(value) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"quantity": _("Enter a valid quantity")}) from None
    if quantity <= 0:
        raise ValidationError({"quantity": _("Quantity must be greater than zero")})
    return quantity


def _check_actor(actor):
    if not (can_approve(actor) or can_handout(actor)):
        raise PermissionDenied("You do not have permission to allocate loan stock")


def _line_allocated_quantity(line) -> Decimal:
    return (
        line.allocations.aggregate(total=Sum("quantity"))["total"] or Decimal(0)
    )


def allocation_data(request: LoanRequest) -> list[dict]:
    """Return allocation records grouped by request line."""
    return [
        {
            "pk": allocation.pk,
            "line_id": allocation.line_id,
            "stock_item": allocation.stock_item_id,
            "stock_item_label": allocation.stock_item_display
            if hasattr(allocation, "stock_item_display")
            else str(allocation.stock_item),
            "stock_item_serial": allocation.stock_item.serial or "",
            "quantity": float(allocation.quantity),
            "created": allocation.created.isoformat(),
        }
        for allocation in LoanRequestAllocation.objects.filter(
            line__request=request
        ).select_related("line", "stock_item", "stock_item__part")
    ]


def _validate_line_allocations(line):
    allocated = _line_allocated_quantity(line)
    if allocated > line.quantity:
        raise ValidationError(
            _("Allocated quantity cannot exceed the requested quantity")
        )


@transaction.atomic
def auto_allocate_request(request: LoanRequest, actor) -> LoanRequest:
    """Replace the request's allocations with an automatic stock allocation."""
    _check_actor(actor)
    request = LoanRequest.objects.select_for_update().get(pk=request.pk)
    if request.status not in {
        LoanRequestStatus.PENDING,
        LoanRequestStatus.APPROVED,
        LoanRequestStatus.PARTIALLY_FULFILLED,
    }:
        raise ValidationError(_("This request can no longer be allocated"))

    LoanRequestAllocation.objects.filter(line__request=request).delete()

    used: dict[int, Decimal] = {}
    for line in request.lines.select_related("part", "stock_item"):
        remaining = line.quantity
        if line.stock_item_id:
            candidates = [line.stock_item]
        else:
            candidates = list(
                available_stock_queryset(line.part)
                .select_for_update()
                .order_by("expiry_date", "updated", "pk")
            )

        for stock_item in candidates:
            if remaining <= 0:
                break
            used_quantity = used.get(stock_item.pk, Decimal(0))
            available = (
                stock_item_available_quantity(stock_item, exclude_request=request)
                - used_quantity
            )
            if available <= 0:
                continue
            if stock_item.serialized:
                take = Decimal(1)
            else:
                take = min(remaining, available)
            if take <= 0:
                continue
            LoanRequestAllocation.objects.create(
                line=line,
                stock_item=stock_item,
                quantity=take,
                created_by=actor,
            )
            used[stock_item.pk] = used_quantity + take
            remaining -= take

        # Partial auto-allocation is allowed.  The API exposes the remaining
        # quantity so the loan desk can see what still needs stock.

    from ..models import LoanEvent, LoanEventType

    LoanEvent.record(
        request=request,
        event_type=LoanEventType.UPDATED,
        actor=actor,
        notes="Automatic stock allocation",
    )
    return request


@transaction.atomic
def add_allocation(
    request: LoanRequest,
    actor,
    *,
    line_id: int,
    stock_item_id: int,
    quantity,
) -> LoanRequestAllocation:
    """Add or update one manual allocation for a request line."""
    _check_actor(actor)
    request = LoanRequest.objects.select_for_update().get(pk=request.pk)
    if request.status not in {
        LoanRequestStatus.PENDING,
        LoanRequestStatus.APPROVED,
        LoanRequestStatus.PARTIALLY_FULFILLED,
    }:
        raise ValidationError(_("This request can no longer be allocated"))

    line = request.lines.filter(pk=line_id).select_related("part").first()
    if line is None:
        raise ValidationError({"line_id": _("The request line does not exist")})

    from stock.models import StockItem

    stock_item = (
        StockItem.objects.select_for_update()
        .filter(pk=stock_item_id)
        .select_related("part")
        .first()
    )
    if stock_item is None:
        raise ValidationError({"stock_item_id": _("The stock item does not exist")})
    if stock_item.part_id not in part_family_ids(line.part):
        raise ValidationError(
            {"stock_item_id": _("The stock item does not belong to this request line")}
        )
    if line.stock_item_id and stock_item.pk != line.stock_item_id:
        raise ValidationError(
            {
                "stock_item_id": _(
                    "This request line is for a specific stock item"
                )
            }
        )

    quantity = _quantity(quantity)
    if stock_item.serialized and quantity != 1:
        raise ValidationError(
            {"quantity": _("A serialized stock item must have quantity 1")}
        )

    used_elsewhere = (
        LoanRequestAllocation.objects.filter(
            line__request=request, stock_item=stock_item
        )
        .exclude(line=line)
        .aggregate(total=Sum("quantity"))["total"]
        or Decimal(0)
    )
    available = (
        stock_item_available_quantity(stock_item, exclude_request=request)
        - used_elsewhere
    )
    if quantity > available:
        raise ValidationError(
            {"quantity": _("Only %(available)s are available") % {"available": available}}
        )

    existing = LoanRequestAllocation.objects.filter(
        line=line, stock_item=stock_item
    ).first()
    allocated = _line_allocated_quantity(line) - (
        existing.quantity if existing else Decimal(0)
    )
    if allocated + quantity > line.quantity:
        raise ValidationError(
            {"quantity": _("Allocated quantity cannot exceed the requested quantity")}
        )

    if existing:
        existing.quantity = quantity
        existing.created_by = actor
        existing.save(update_fields=["quantity", "created_by", "updated"])
        return existing

    allocation = LoanRequestAllocation.objects.create(
        line=line,
        stock_item=stock_item,
        quantity=quantity,
        created_by=actor,
    )
    _validate_line_allocations(line)
    return allocation


@transaction.atomic
def remove_allocation(request: LoanRequest, actor, allocation_id: int) -> None:
    """Remove one manual allocation."""
    _check_actor(actor)
    request = LoanRequest.objects.select_for_update().get(pk=request.pk)
    if request.status not in {
        LoanRequestStatus.PENDING,
        LoanRequestStatus.APPROVED,
        LoanRequestStatus.PARTIALLY_FULFILLED,
    }:
        raise ValidationError(_("This request can no longer be allocated"))
    allocation = LoanRequestAllocation.objects.filter(
        pk=allocation_id, line__request=request
    ).first()
    if allocation is None:
        raise ValidationError(_("The allocation does not exist"))
    allocation.delete()


@transaction.atomic
def clear_allocations(request: LoanRequest, actor) -> None:
    """Remove every allocation from a request."""
    _check_actor(actor)
    request = LoanRequest.objects.select_for_update().get(pk=request.pk)
    if request.status not in {
        LoanRequestStatus.PENDING,
        LoanRequestStatus.APPROVED,
        LoanRequestStatus.PARTIALLY_FULFILLED,
    }:
        raise ValidationError(_("This request can no longer be allocated"))
    LoanRequestAllocation.objects.filter(line__request=request).delete()
