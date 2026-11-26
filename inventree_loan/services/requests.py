"""Request creation and decision services."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..config import get_loanable_category, get_setting
from ..models import (
    Loan,
    LoanEvent,
    LoanEventType,
    LoanRequest,
    LoanRequestLine,
    LoanRequestStatus,
)
from ..permissions import can_request
from ..utils import clean_signature, local_today
from .notifications import notify_request_decided, notify_request_submitted


def _decimal(value, default=Decimal("1")) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"quantity": _("Enter a valid quantity")}) from None


def _loan_location():
    from .setup import get_loan_location

    return get_loan_location()


def part_family_ids(part) -> list[int]:
    """Return the part and its variant/descendant part IDs.

    InvenTree template parts usually hold no stock themselves; their stock is
    held by variant parts.  Availability and allocation must therefore consider
    the whole variant family.
    """
    if part is None:
        return []
    if not getattr(part, "is_template", False):
        return [part.pk]
    try:
        ids = list(
            part.get_descendants(include_self=True).values_list("pk", flat=True)
        )
    except Exception:  # pragma: no cover - defensive for unusual part loaders
        ids = [part.pk]
    return ids or [part.pk]


def _active_loan_stock_ids():
    from ..models import LoanItem

    return LoanItem.objects.filter(returned_at__isnull=True, lost=False).values(
        "stock_item_id"
    )


def loan_allocated_quantity(stock_item, exclude_request=None) -> Decimal:
    """Return the quantity of a stock item reserved by live loan requests."""
    from ..models import LoanRequestAllocation, LoanRequestStatus

    queryset = LoanRequestAllocation.objects.filter(
        stock_item=stock_item,
        line__request__status__in=[
            LoanRequestStatus.PENDING,
            LoanRequestStatus.APPROVED,
            LoanRequestStatus.PARTIALLY_FULFILLED,
        ],
    )
    if exclude_request is not None:
        queryset = queryset.exclude(line__request=exclude_request)
    return queryset.aggregate(total=Sum("quantity"))["total"] or Decimal(0)


def available_stock_queryset(part=None, part_ids=None):
    """Return stock items for a part family that may currently be loaned."""
    from stock.models import StockItem
    from stock.status_codes import StockStatusGroups

    if part is not None:
        part_ids = part_family_ids(part)
    if not part_ids:
        return StockItem.objects.none()

    queryset = StockItem.objects.filter(
        part_id__in=part_ids,
        part__active=True,
        part__virtual=False,
        quantity__gt=0,
        location__isnull=False,
        customer__isnull=True,
        sales_order__isnull=True,
        belongs_to__isnull=True,
        build__isnull=True,
        status__in=StockStatusGroups.AVAILABLE_CODES,
    ).exclude(pk__in=_active_loan_stock_ids())

    location = _loan_location()
    if location is not None:
        queryset = queryset.exclude(location=location)
    return queryset


def stock_item_available_quantity(item, exclude_request=None) -> Decimal:
    """Return the quantity of a stock item that can be loaned right now."""
    if item is None or item.quantity <= 0:
        return Decimal(0)
    if not item.is_in_stock():
        return Decimal(0)
    location = _loan_location()
    if location is not None and item.location_id == location.pk:
        return Decimal(0)
    from ..models import LoanItem

    if LoanItem.objects.filter(
        stock_item=item, returned_at__isnull=True, lost=False
    ).exists():
        return Decimal(0)
    reserved = loan_allocated_quantity(item, exclude_request=exclude_request)
    return max(item.unallocated_quantity() - reserved, Decimal(0))


def stock_item_available_bulk(items, exclude_request=None) -> dict[int, Decimal]:
    """Return available quantities for many stock items in a fixed query count."""
    from stock.models import StockItem

    from ..models import LoanItem, LoanRequestAllocation, LoanRequestStatus

    items = list(items)
    if not items:
        return {}

    # `bulk_allocation_count` is available on InvenTree 1.7+.  Fall back to
    # the per-item calculation on 1.6 so the plugin keeps its supported range.
    bulk_allocations = (
        StockItem.bulk_allocation_count(items)
        if hasattr(StockItem, "bulk_allocation_count")
        else None
    )
    loan_reserved = {
        row["stock_item"]: row["total"]
        for row in LoanRequestAllocation.objects.filter(
            stock_item__in=items,
            line__request__status__in=[
                LoanRequestStatus.PENDING,
                LoanRequestStatus.APPROVED,
                LoanRequestStatus.PARTIALLY_FULFILLED,
            ],
        )
        .exclude(line__request=exclude_request)
        .values("stock_item")
        .annotate(total=Sum("quantity"))
    }
    open_loan_items = set(
        LoanItem.objects.filter(
            stock_item__in=items, returned_at__isnull=True, lost=False
        ).values_list("stock_item_id", flat=True)
    )

    result = {}
    for item in items:
        if item.pk in open_loan_items:
            result[item.pk] = Decimal(0)
            continue
        allocated = (
            item.unallocated_quantity()
            if bulk_allocations is None
            else item.quantity - bulk_allocations.get(item.pk, Decimal(0))
        )
        result[item.pk] = max(
            allocated - loan_reserved.get(item.pk, Decimal(0)), Decimal(0)
        )
    return result


def part_availability_bulk(parts, exclude_request=None) -> dict[int, dict]:
    """Return availability for many parts using a fixed number of queries.

    This is the hot path for the public catalogue.  Computing availability one
    part at a time causes an N+1 explosion across stock items, open loans and
    loan allocations.
    """
    from ..models import LoanItem

    parts = list(parts)
    if not parts:
        return {}

    families = {part.pk: part_family_ids(part) for part in parts}
    all_part_ids = set()
    for ids in families.values():
        all_part_ids.update(ids)

    items = list(
        available_stock_queryset(part_ids=list(all_part_ids)).select_related("part")
    )
    item_available = stock_item_available_bulk(
        items, exclude_request=exclude_request
    )
    items_by_part: dict[int, list[int]] = {}
    for item in items:
        if item_available.get(item.pk, Decimal(0)) > 0:
            items_by_part.setdefault(item.part_id, []).append(item.pk)

    remaining = ExpressionWrapper(
        F("quantity") - F("returned_quantity"),
        output_field=DecimalField(max_digits=15, decimal_places=5),
    )
    on_loan_by_part = {
        row["part_id"]: row["total"]
        for row in LoanItem.objects.filter(
            part_id__in=all_part_ids, returned_at__isnull=True, lost=False
        )
        .values("part_id")
        .annotate(total=Sum(remaining))
    }

    result = {}
    for part in parts:
        ids = set(families[part.pk])
        available = sum(
            (
                item_available[item_pk]
                for part_id in ids
                for item_pk in items_by_part.get(part_id, [])
            ),
            Decimal(0),
        )
        on_loan = sum(
            (on_loan_by_part.get(part_id, Decimal(0)) for part_id in ids),
            Decimal(0),
        )
        result[part.pk] = {
            "available": available,
            "on_loan": on_loan,
            "total": available + on_loan,
        }
    return result


def part_availability(part, exclude_request=None) -> dict:
    """Return available and on-loan quantities for a part family."""
    return part_availability_bulk([part], exclude_request=exclude_request).get(
        part.pk,
        {"available": Decimal(0), "on_loan": Decimal(0), "total": Decimal(0)},
    )


def _part_image(part):
    if not part.image:
        return None
    from django.urls import reverse

    try:
        return reverse("plugin:loan:api_public_part_image", args=[part.pk])
    except Exception:  # pragma: no cover
        return None


def catalog_part_count() -> int:
    """Return the number of parts visible in the public catalogue."""
    from part.models import Part

    queryset = Part.objects.filter(active=True, virtual=False)
    base = get_loanable_category()
    if base:
        queryset = queryset.filter(
            Q(category__pathstring=base.pathstring)
            | Q(category__pathstring__startswith=f"{base.pathstring}/")
        )
    return queryset.count()


def catalog_categories() -> list[dict]:
    """Return the category tree available to public requesters."""
    from part.models import Part, PartCategory

    base = get_loanable_category()

    # Only expose branches which contain at least one active part.  Empty
    # placeholder categories make the public catalogue harder to browse.
    part_paths = (
        Part.objects.filter(active=True, virtual=False, category__isnull=False)
        .values_list("category__pathstring", flat=True)
        .distinct()
    )
    prefixes = set()
    for path in part_paths:
        if not path:
            continue
        bits = path.split("/")
        for index in range(1, len(bits) + 1):
            prefixes.add("/".join(bits[:index]))

    queryset = PartCategory.objects.filter(pathstring__in=prefixes)
    if base:
        queryset = queryset.filter(
            Q(pathstring=base.pathstring)
            | Q(pathstring__startswith=f"{base.pathstring}/")
        )

    exact_counts = {
        row["category_id"]: row["total"]
        for row in Part.objects.filter(
            active=True, virtual=False, category__isnull=False
        )
        .values("category_id")
        .annotate(total=Count("pk"))
    }

    category_rows = list(queryset.order_by("tree_id", "lft"))
    parent_ids = {category.parent_id for category in category_rows if category.parent_id}

    # A category filter includes all of its descendants, so the number shown
    # next to a category must include descendant parts too.
    rolled_counts = {}
    for category in category_rows:
        count = exact_counts.get(category.pk, 0)
        if not count:
            continue
        bits = category.pathstring.split("/")
        for index in range(1, len(bits) + 1):
            path = "/".join(bits[:index])
            rolled_counts[path] = rolled_counts.get(path, 0) + count

    return [
        {
            "pk": category.pk,
            "name": category.name,
            "parent": category.parent_id,
            "path": category.pathstring,
            "depth": category.pathstring.count("/"),
            "part_count": rolled_counts.get(category.pathstring, 0),
            "has_children": category.pk in parent_ids,
        }
        for category in category_rows
    ]


def catalog_parts(
    search: str = "",
    limit: int = 20,
    category_id: int | None = None,
    offset: int = 0,
) -> dict:
    """Return a limited, requester-safe part catalog."""
    from part.models import Part, PartCategory

    queryset = Part.objects.filter(active=True, virtual=False).select_related("category")
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(IPN__icontains=search)
            | Q(description__icontains=search)
        )

    base = get_loanable_category()
    if base:
        queryset = queryset.filter(
            Q(category__pathstring=base.pathstring)
            | Q(category__pathstring__startswith=f"{base.pathstring}/")
        )

    if category_id:
        category = PartCategory.objects.filter(pk=category_id).first()
        if category:
            queryset = queryset.filter(
                Q(category__pathstring=category.pathstring)
                | Q(category__pathstring__startswith=f"{category.pathstring}/")
            )

    total = queryset.count()
    page_parts = list(queryset.order_by("name")[offset : offset + limit])
    availability_map = part_availability_bulk(page_parts)
    results = []
    for part in page_parts:
        availability = availability_map.get(
            part.pk,
            {"available": Decimal(0), "on_loan": Decimal(0)},
        )
        is_template = bool(getattr(part, "is_template", False))
        variant_count = (
            max(part.get_descendant_count(), 0) if is_template else 0
        )
        results.append({
            "pk": part.pk,
            "name": part.name,
            "ipn": part.IPN or "",
            "description": part.description or "",
            "category": part.category.name if part.category else "",
            "category_id": part.category_id,
            "units": getattr(part, "units", "") or "",
            "trackable": bool(getattr(part, "trackable", False)),
            "is_template": is_template,
            "variant_count": variant_count,
            "available": float(availability["available"]),
            "on_loan": float(availability["on_loan"]),
            "image": _part_image(part),
        })
    return {"results": results, "total": total, "offset": offset, "limit": limit}


def part_detail(
    part_id: int, exclude_request=None, include_stock_items: bool = True
) -> dict | None:
    """Return public part details and the individual units available to loan."""
    from part.models import Part

    part = (
        Part.objects.select_related("category")
        .filter(pk=part_id, active=True, virtual=False)
        .first()
    )
    if part is None:
        return None

    base = get_loanable_category()
    if base and (
        not part.category
        or not (
            part.category.pathstring == base.pathstring
            or part.category.pathstring.startswith(f"{base.pathstring}/")
        )
    ):
        return None

    availability = part_availability(part, exclude_request=exclude_request)
    stock_items = []
    if include_stock_items:
        page_items = list(
            available_stock_queryset(part)
            .select_related("location", "part")
            .order_by("serial", "batch", "pk")[:100]
        )
        item_available = stock_item_available_bulk(
            page_items, exclude_request=exclude_request
        )
        for item in page_items:
            available = item_available.get(item.pk, Decimal(0))
            if available <= 0:
                continue
            stock_items.append({
                "pk": item.pk,
                "part": item.part_id,
                "part_name": item.part.name,
                "ipn": item.part.IPN or "",
                "label": item.serial or item.batch or f"Item #{item.pk}",
                "serial": item.serial or "",
                "batch": item.batch or "",
                "quantity": float(item.quantity),
                "available": float(available),
                "location": item.location.pathstring if item.location else "",
                "serialized": bool(item.serialized),
                "trackable": bool(getattr(item.part, "trackable", False)),
            })

    is_template = bool(getattr(part, "is_template", False))
    variants = []
    variant_count = 0
    if is_template:
        family = part_family_ids(part)
        variant_parts = list(
            Part.objects.filter(pk__in=family, active=True, virtual=False)
            .exclude(pk=part.pk)
            .order_by("name")
        )
        variant_count = len(variant_parts)
        variant_availability = part_availability_bulk(
            variant_parts, exclude_request=exclude_request
        )
        variants = [
            {
                "pk": variant.pk,
                "name": variant.name,
                "ipn": variant.IPN or "",
                "trackable": bool(getattr(variant, "trackable", False)),
                "available": float(
                    variant_availability.get(
                        variant.pk, {"available": Decimal(0)}
                    )["available"]
                ),
            }
            for variant in variant_parts
        ]

    result = {
        "pk": part.pk,
        "name": part.name,
        "ipn": part.IPN or "",
        "description": part.description or "",
        "category": part.category.name if part.category else "",
        "category_id": part.category_id,
        "units": getattr(part, "units", "") or "",
        "trackable": bool(getattr(part, "trackable", False)),
        "is_template": is_template,
        "variant_count": variant_count,
        "variants": variants,
        "available": float(availability["available"]),
        "on_loan": float(availability["on_loan"]),
        "image": _part_image(part),
    }
    if include_stock_items:
        result["stock_items"] = stock_items
    return result


def _validate_dates(needed_by, return_by):
    today = local_today()
    needed_by = needed_by or today
    if needed_by < today:
        raise ValidationError({"needed_by": _("Pickup date cannot be in the past")})

    if return_by is None:
        days = int(get_setting("LOAN_DURATION_DAYS", 14) or 14)
        return_by = needed_by + timedelta(days=max(days, 1))
    if return_by < needed_by:
        raise ValidationError(
            {"return_by": _("Return date must be on or after the pickup date")}
        )
    return needed_by, return_by


def _validate_lines(lines: list[dict]) -> list[dict]:
    from part.models import Part
    from stock.models import StockItem

    if not lines:
        raise ValidationError({"lines": _("At least one item is required")})

    max_items = int(get_setting("MAX_ITEMS_PER_REQUEST", 25) or 25)
    if len(lines) > max_items:
        raise ValidationError({"lines": _("Too many items in one request")})

    category = get_loanable_category()
    cleaned = []

    for raw in lines:
        part_id = raw.get("part_id") or raw.get("part")
        part = raw.get("part") if isinstance(raw.get("part"), Part) else None
        if part is None:
            if not part_id:
                raise ValidationError({"lines": _("Each line requires a part")})
            try:
                part = Part.objects.get(pk=part_id)
            except (Part.DoesNotExist, ValueError, TypeError):
                raise ValidationError({"lines": _("A selected part no longer exists")}) from None

        if not part.active:
            raise ValidationError({"lines": _("Inactive parts cannot be requested")})
        if category and (
            not part.category
            or not (
                part.category.pathstring == category.pathstring
                or part.category.pathstring.startswith(f"{category.pathstring}/")
            )
        ):
            raise ValidationError(
                {"lines": _("This part is not in the loanable category")}
            )

        quantity = _decimal(raw.get("quantity"), Decimal("1"))
        if quantity <= 0:
            raise ValidationError({"quantity": _("Quantity must be greater than zero")})
        if getattr(part, "trackable", False) and quantity != quantity.to_integral_value():
            raise ValidationError(
                {"quantity": _("Trackable parts must be requested in whole units")}
            )

        stock_item = raw.get("stock_item") if isinstance(raw.get("stock_item"), StockItem) else None
        stock_item_id = raw.get("stock_item_id") or raw.get("stock_item")
        if stock_item is None and stock_item_id:
            try:
                stock_item = StockItem.objects.get(pk=stock_item_id)
            except (StockItem.DoesNotExist, ValueError, TypeError):
                raise ValidationError(
                    {"stock_item": _("The selected stock item no longer exists")}
                ) from None

        if stock_item is not None:
            if stock_item.part_id not in part_family_ids(part):
                raise ValidationError(
                    {"stock_item": _("The stock item does not belong to the selected part")}
                )
            if stock_item.serialized:
                quantity = Decimal(1)
            available = stock_item_available_quantity(stock_item)
            if available <= 0:
                raise ValidationError(
                    {"stock_item": _("This stock item is not available to loan")}
                )
            if quantity > available:
                raise ValidationError(
                    {"quantity": _("Only %(available)s are available") % {"available": available}}
                )
        else:
            availability = part_availability(part)
            available = availability["available"]
            if available <= 0:
                raise ValidationError(
                    {"lines": _("%(part)s is not available to loan") % {"part": part}}
                )
            if quantity > available:
                raise ValidationError(
                    {
                        "quantity": _("Only %(available)s of %(part)s are available")
                        % {"available": available, "part": part}
                    }
                )

        cleaned.append({
            "part": part,
            "stock_item": stock_item,
            "quantity": quantity,
            "notes": (raw.get("notes") or "").strip(),
        })

    return cleaned


def _check_active_loan_limit(user):
    limit = int(get_setting("MAX_ACTIVE_LOANS_PER_USER", 0) or 0)
    if limit <= 0:
        return
    active = Loan.objects.filter(
        borrower=user, status__in=["active", "partially_returned", "overdue"]
    ).count()
    if active >= limit:
        raise ValidationError(
            _("This user already has the maximum number of active loans")
        )


@transaction.atomic
def create_request(
    user,
    lines: list[dict],
    *,
    purpose: str = "",
    needed_by: date | None = None,
    return_by: date | None = None,
    notes: str = "",
    contact: str = "",
    project: str = "",
    responsibility_ack: bool = False,
    requester_name: str = "",
    requester_email: str = "",
    requester_phone: str = "",
    requester_organization: str = "",
    requester_identifier: str = "",
    signature: str = "",
    allow_anonymous: bool = False,
    require_signature: bool = True,
) -> LoanRequest:
    """Create a loan request with validated lines.

    Authenticated requesters use their account; anonymous requesters provide
    their own contact details and signature through the public form.
    """
    if user is None:
        if not allow_anonymous:
            raise PermissionDenied("You do not have permission to request loans")
        requester_name = (requester_name or "").strip()
        requester_email = (requester_email or "").strip()
        if not requester_name:
            raise ValidationError({"requester_name": _("Enter your name")})
        if not requester_email:
            raise ValidationError({"requester_email": _("Enter your email address")})
        from django.core.validators import validate_email

        try:
            validate_email(requester_email)
        except Exception:
            raise ValidationError(
                {"requester_email": _("Enter a valid email address")}
            ) from None
    else:
        if not can_request(user):
            raise PermissionDenied("You do not have permission to request loans")
        requester_name = (
            (requester_name or "").strip()
            or user.get_full_name()
            or user.username
        )
        requester_email = (requester_email or "").strip() or user.email
        requester_phone = (requester_phone or "").strip() or (contact or "").strip()

    if get_setting("REQUIRE_RESPONSIBILITY_ACK", True) and not responsibility_ack:
        raise ValidationError(
            {"responsibility_ack": _("Please acknowledge the loan responsibility statement")}
        )
    if not (purpose or "").strip():
        raise ValidationError({"purpose": _("Please describe the purpose of the loan")})

    require_signature = require_signature and bool(
        get_setting("REQUIRE_REQUEST_SIGNATURE", True)
    )
    signature = clean_signature(signature, required=require_signature)

    for raw in lines:
        if raw.get("stock_item") or raw.get("stock_item_id"):
            raise ValidationError(
                {
                    "lines": _(
                        "Choose a part; the loan desk assigns the stock item"
                    )
                }
            )
    if user is not None:
        _check_active_loan_limit(user)
    cleaned = _validate_lines(lines)
    needed_by, return_by = _validate_dates(needed_by, return_by)

    request = LoanRequest.objects.create(
        requester=user,
        requester_name=requester_name,
        requester_email=requester_email,
        requester_phone=(requester_phone or "").strip(),
        requester_organization=(requester_organization or "").strip(),
        requester_identifier=(requester_identifier or "").strip(),
        signature=signature,
        purpose=(purpose or "").strip(),
        needed_by=needed_by,
        return_by=return_by,
        notes=(notes or "").strip(),
        contact=(contact or "").strip(),
        project=(project or "").strip(),
        responsibility_ack=responsibility_ack,
    )

    for line in cleaned:
        LoanRequestLine.objects.create(
            request=request,
            part=line["part"],
            stock_item=line["stock_item"],
            quantity=line["quantity"],
            notes=line["notes"],
        )

    LoanEvent.record(
        request=request,
        event_type=LoanEventType.REQUESTED,
        actor=user,
        actor_name="" if user is not None else requester_name,
        notes=(purpose or "").strip(),
        lines=len(cleaned),
        signed=bool(signature),
    )
    notify_request_submitted(request)
    return request


@transaction.atomic
def approve_request(request: LoanRequest, actor, notes: str = "") -> LoanRequest:
    """Approve a pending request."""
    from ..permissions import can_approve

    if not can_approve(actor):
        raise PermissionDenied("You do not have permission to approve requests")

    request = LoanRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != LoanRequestStatus.PENDING:
        raise ValidationError(_("Only pending requests can be approved"))

    request.status = LoanRequestStatus.APPROVED
    request.decided_by = actor
    request.decided_at = timezone.now()
    request.decision_notes = (notes or "").strip()
    request.save(update_fields=["status", "decided_by", "decided_at", "decision_notes", "updated"])

    LoanEvent.record(
        request=request,
        event_type=LoanEventType.APPROVED,
        actor=actor,
        notes=(notes or "").strip(),
    )
    notify_request_decided(request)
    return request


@transaction.atomic
def reject_request(request: LoanRequest, actor, notes: str = "") -> LoanRequest:
    """Reject a pending request."""
    from ..permissions import can_approve

    if not can_approve(actor):
        raise PermissionDenied("You do not have permission to reject requests")

    request = LoanRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != LoanRequestStatus.PENDING:
        raise ValidationError(_("Only pending requests can be rejected"))

    from ..models import LoanRequestAllocation

    LoanRequestAllocation.objects.filter(line__request=request).delete()
    request.status = LoanRequestStatus.REJECTED
    request.decided_by = actor
    request.decided_at = timezone.now()
    request.decision_notes = (notes or "").strip()
    request.save(update_fields=["status", "decided_by", "decided_at", "decision_notes", "updated"])

    LoanEvent.record(
        request=request,
        event_type=LoanEventType.REJECTED,
        actor=actor,
        notes=(notes or "").strip(),
    )
    notify_request_decided(request)
    return request


@transaction.atomic
def cancel_request(request: LoanRequest, actor, notes: str = "") -> LoanRequest:
    """Cancel a request, respecting ownership and state."""
    from ..permissions import can_cancel_request

    if not can_cancel_request(actor, request):
        raise PermissionDenied("You cannot cancel this request")

    request = LoanRequest.objects.select_for_update().get(pk=request.pk)
    if request.status in {
        LoanRequestStatus.FULFILLED,
        LoanRequestStatus.REJECTED,
        LoanRequestStatus.CANCELLED,
    }:
        raise ValidationError(_("This request can no longer be cancelled"))

    from ..models import LoanRequestAllocation

    LoanRequestAllocation.objects.filter(line__request=request).delete()
    request.status = LoanRequestStatus.CANCELLED
    request.decided_by = actor
    request.decided_at = timezone.now()
    request.decision_notes = (notes or "").strip()
    request.save(update_fields=["status", "decided_by", "decided_at", "decision_notes", "updated"])

    LoanEvent.record(
        request=request,
        event_type=LoanEventType.CANCELLED,
        actor=actor,
        notes=(notes or "").strip(),
    )
    return request
