"""JSON API for the loan plugin."""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from ..config import (
    get_frontend_base,
    get_public_field_config,
    get_public_request_url,
    get_setting,
)
from ..models import (
    Loan,
    LoanEvent,
    LoanItem,
    LoanPickup,
    LoanRequest,
    LoanRequestAllocation,
    LoanRequestCustomField,
    LoanRequestLine,
    LoanStaff,
    LoanStaffRole,
)
from ..permissions import (
    can_approve,
    can_handout,
    can_manage_staff,
    can_request,
    can_view_all,
    get_user_role,
)
from ..selectors import (
    loan_with_items,
    request_with_lines,
    visible_events,
    visible_loans,
    visible_requests,
)
from ..services.allocation import (
    add_allocation,
    auto_allocate_request,
    clear_allocations,
    remove_allocation,
)
from ..services.barcode import generate_qr_svg, generate_qr_svg_payload, resolve_barcode
from ..services.checkout import checkout_direct, checkout_request
from ..services.requests import (
    approve_request,
    cancel_request,
    catalog_categories,
    catalog_parts,
    create_request,
    part_availability,
    part_availability_bulk,
    part_detail,
    reject_request,
)
from ..services.pickups import mark_ready_for_pickup
from ..services.custom_fields import custom_field_values
from ..services.returns import mark_lost, renew_loan, return_loan
from ..services.setup import (
    ensure_setup,
    get_loan_location,
    get_on_loan_status,
    is_configured,
)
from .serializers import (
    ApproveSerializer,
    CheckoutSerializer,
    CustomFieldSerializer,
    DecisionSerializer,
    LostSerializer,
    PublicRequestCreateSerializer,
    PublicRequestLookupSerializer,
    ReadyForPickupSerializer,
    RenewSerializer,
    RequestAllocateSerializer,
    RequestCreateSerializer,
    ReturnSerializer,
    ScanSerializer,
    StaffCreateSerializer,
    StaffUpdateSerializer,
)


def _iso(value):
    return value.isoformat() if value else None


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _web_url(path: str) -> str:
    return f"/{get_frontend_base()}{path}"


REQUEST_OPEN_STATUSES = [
    "pending",
    "approved",
    "partially_approved",
    "ready_for_pickup",
    "partially_fulfilled",
]
REQUEST_CLOSED_STATUSES = ["fulfilled", "rejected", "cancelled"]
LOAN_OPEN_STATUSES = ["active", "partially_returned", "overdue"]
LOAN_CLOSED_STATUSES = ["returned", "cancelled", "lost"]

REQUEST_SORTS = {
    "created": "created",
    "-created": "-created",
    "reference": "reference",
    "-reference": "-reference",
    "status": "status",
    "-status": "-status",
    "requester": ("requester_name", "requester__username"),
    "-requester": ("-requester_name", "-requester__username"),
    "needed_by": "needed_by",
    "-needed_by": "-needed_by",
    "return_by": "return_by",
    "-return_by": "-return_by",
    "items": "item_count_annotated",
    "-items": "-item_count_annotated",
}

LOAN_SORTS = {
    "issued_at": "issued_at",
    "-issued_at": "-issued_at",
    "due_at": "due_at",
    "-due_at": "-due_at",
    "reference": "reference",
    "-reference": "-reference",
    "status": "status",
    "-status": "-status",
    "borrower": ("borrower_name", "borrower__username"),
    "-borrower": ("-borrower_name", "-borrower__username"),
    "returned_at": "returned_at",
    "-returned_at": "-returned_at",
    "items": "item_count_annotated",
    "-items": "-item_count_annotated",
}


def _list_permissions(user) -> dict:
    """Resolve role checks once for a list response instead of once per row."""
    return {
        "can_approve": can_approve(user),
        "can_handout": can_handout(user),
    }


def _int_param(request, name: str, default: int, maximum: int | None = None) -> int:
    try:
        value = int(request.GET.get(name, default))
    except (TypeError, ValueError):
        value = default
    value = max(value, 0)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _limit_param(request, default: int = 25, maximum: int = 100) -> int:
    return max(_int_param(request, "limit", default, maximum), 1)


def _page_params(request, default_limit: int = 25) -> tuple[int, int]:
    return _limit_param(request, default_limit), _int_param(request, "offset", 0)


def _request_list_queryset(user):
    """Requests with cheap aggregate annotations for list and CSV views."""
    line_totals = (
        LoanRequestLine.objects.filter(request=OuterRef("pk"))
        .values("request")
        .annotate(
            total=Sum("quantity"),
            approved=Sum("approved_quantity"),
            count=Count("pk"),
        )
    )
    allocated_totals = (
        LoanRequestAllocation.objects.filter(line__request=OuterRef("pk"))
        .values("line__request")
        .annotate(total=Sum("quantity"))
    )
    return visible_requests(user).annotate(
        item_count_annotated=Coalesce(
            Subquery(line_totals.values("count")[:1]), Value(0)
        ),
        total_quantity_annotated=Coalesce(
            Subquery(line_totals.values("total")[:1]),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=15, decimal_places=5),
        ),
        approved_quantity_annotated=Coalesce(
            Subquery(line_totals.values("approved")[:1]),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=15, decimal_places=5),
        ),
        allocated_quantity_annotated=Coalesce(
            Subquery(allocated_totals.values("total")[:1]),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=15, decimal_places=5),
        ),
    )


def _filter_request_list(queryset, params):
    search = params.get("search", "").strip()
    if search:
        queryset = queryset.filter(
            Q(reference__icontains=search)
            | Q(loan__reference__icontains=search)
            | Q(pickup__reference__icontains=search)
            | Q(pickup__name__icontains=search)
            | Q(requester__username__icontains=search)
            | Q(requester__first_name__icontains=search)
            | Q(requester__last_name__icontains=search)
            | Q(requester__email__icontains=search)
            | Q(requester_name__icontains=search)
            | Q(requester_email__icontains=search)
            | Q(purpose__icontains=search)
            | Q(notes__icontains=search)
            | Q(lines__part__name__icontains=search)
            | Q(lines__part__IPN__icontains=search)
        ).distinct()

    raw_status = params.get("status", "").strip()
    if raw_status:
        statuses = []
        for token in raw_status.split(","):
            token = token.strip()
            if token == "open":
                statuses.extend(REQUEST_OPEN_STATUSES)
            elif token == "closed":
                statuses.extend(REQUEST_CLOSED_STATUSES)
            elif token:
                statuses.append(token)
        if statuses:
            queryset = queryset.filter(status__in=statuses)

    allocation = params.get("allocation", "").strip()
    if allocation in {"complete", "incomplete"}:
        # Only open requests still need allocation.  Closed or fulfilled
        # requests should not appear as "needs allocation" forever.
        queryset = queryset.filter(status__in=REQUEST_OPEN_STATUSES)
        if allocation == "complete":
            queryset = queryset.filter(
                allocated_quantity_annotated__gte=F("total_quantity_annotated")
            )
        else:
            queryset = queryset.filter(
                allocated_quantity_annotated__lt=F("total_quantity_annotated")
            )
    return queryset


def _request_sort(queryset, params):
    sort = params.get("sort", "-created")
    order = REQUEST_SORTS.get(sort, "-created")
    if isinstance(order, tuple):
        return queryset.order_by(*order, "-pk")
    return queryset.order_by(order, "-pk")


def _request_summary_data(
    loan_request, user, require_approval: bool = True, permissions: dict | None = None
) -> dict:
    loan = getattr(loan_request, "loan", None)
    permissions = permissions or _list_permissions(user)
    total_quantity = (
        getattr(loan_request, "total_quantity_annotated", Decimal("0")) or Decimal("0")
    )
    approved_quantity = (
        getattr(loan_request, "approved_quantity_annotated", Decimal("0"))
        or Decimal("0")
    )
    allocated_quantity = (
        getattr(loan_request, "allocated_quantity_annotated", Decimal("0"))
        or Decimal("0")
    )
    item_count = int(getattr(loan_request, "item_count_annotated", 0) or 0)
    status = loan_request.status
    approve = permissions["can_approve"]
    handout = permissions["can_handout"]
    return {
        "pk": loan_request.pk,
        "reference": loan_request.reference,
        "status": status,
        "status_display": loan_request.get_status_display(),
        "requester": loan_request.requester_display,
        "requester_id": loan_request.requester_id,
        "requester_name": loan_request.requester_display,
        "requester_email": loan_request.requester_email_display,
        "public_token": str(loan_request.public_token),
        "track_url": (
            reverse(
                "plugin:loan:public_request_detail",
                args=[loan_request.public_token],
            )
            if loan_request.requester_id is None
            else ""
        ),
        "request_url": _web_url(f"/plugin/loan/requests/{loan_request.pk}"),
        "purpose": loan_request.purpose,
        "needed_by": _iso(loan_request.needed_by),
        "return_by": _iso(loan_request.return_by),
        "created": _iso(loan_request.created),
        "decided_at": _iso(loan_request.decided_at),
        "item_count": item_count,
        "total_quantity": _num(total_quantity),
        "approved_quantity": _num(approved_quantity),
        "allocated_quantity": _num(allocated_quantity),
        "is_fully_approved": total_quantity > 0
        and approved_quantity >= total_quantity,
        "is_fully_allocated": approved_quantity > 0
        and allocated_quantity >= approved_quantity,
        "loan_pk": loan.pk if loan else None,
        "loan_reference": loan.reference if loan else "",
        "loan_status": loan.status if loan else "",
        "loan_status_display": loan.get_status_display() if loan else "",
        "loan_returned_at": _iso(loan.returned_at) if loan else None,
        "pickup": _pickup_data(getattr(loan_request, "pickup", None)),
        "can_approve": approve
        and status in {"pending", "partially_approved"},
        "can_handout": handout,
        "can_mark_ready": approve
        and status in {"approved", "partially_approved", "ready_for_pickup"},
        "can_cancel": status in REQUEST_OPEN_STATUSES,
        "can_checkout": handout
        and (
            status in {"approved", "partially_approved", "ready_for_pickup"}
            or (status == "pending" and not require_approval)
        ),
    }


def _loan_list_queryset(user):
    """Loans with cheap aggregate annotations for list and CSV views."""
    item_totals = (
        LoanItem.objects.filter(loan=OuterRef("pk"))
        .values("loan")
        .annotate(
            total=Sum("quantity"),
            remaining=Sum(
                ExpressionWrapper(
                    F("quantity") - F("returned_quantity"),
                    output_field=DecimalField(max_digits=15, decimal_places=5),
                )
            ),
            count=Count("pk"),
        )
    )
    return visible_loans(user).annotate(
        item_count_annotated=Coalesce(
            Subquery(item_totals.values("count")[:1]), Value(0)
        ),
        total_quantity_annotated=Coalesce(
            Subquery(item_totals.values("total")[:1]),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=15, decimal_places=5),
        ),
        remaining_quantity_annotated=Coalesce(
            Subquery(item_totals.values("remaining")[:1]),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=15, decimal_places=5),
        ),
    )


def _filter_loan_list(queryset, params):
    search = params.get("search", "").strip()
    if search:
        queryset = queryset.filter(
            Q(reference__icontains=search)
            | Q(borrower__username__icontains=search)
            | Q(borrower__first_name__icontains=search)
            | Q(borrower__last_name__icontains=search)
            | Q(borrower__email__icontains=search)
            | Q(borrower_name__icontains=search)
            | Q(borrower_email__icontains=search)
            | Q(borrower_phone__icontains=search)
            | Q(notes__icontains=search)
            | Q(request__reference__icontains=search)
            | Q(items__part__name__icontains=search)
            | Q(items__part__IPN__icontains=search)
        ).distinct()

    raw_status = params.get("status", "").strip()
    if raw_status:
        now = timezone.now()
        due_soon_days = int(get_setting("DUE_SOON_DAYS", 2) or 2)
        status_query = Q()
        for token in raw_status.split(","):
            token = token.strip()
            if token == "open":
                status_query |= Q(status__in=LOAN_OPEN_STATUSES)
            elif token == "closed":
                status_query |= Q(status__in=LOAN_CLOSED_STATUSES)
            elif token == "overdue":
                status_query |= Q(status__in=LOAN_OPEN_STATUSES, due_at__lt=now)
            elif token == "due_soon":
                status_query |= Q(
                    status__in=LOAN_OPEN_STATUSES,
                    due_at__gte=now,
                    due_at__lte=now + timedelta(days=due_soon_days),
                )
            elif token:
                status_query |= Q(status=token)
        if status_query:
            queryset = queryset.filter(status_query)
    return queryset


def _loan_sort(queryset, params):
    sort = params.get("sort", "-issued_at")
    order = LOAN_SORTS.get(sort, "-issued_at")
    if isinstance(order, tuple):
        return queryset.order_by(*order, "-pk")
    return queryset.order_by(order, "-pk")


def _loan_summary_data(loan, user, permissions: dict | None = None) -> dict:
    permissions = permissions or _list_permissions(user)
    handout = permissions["can_handout"]
    total_quantity = (
        getattr(loan, "total_quantity_annotated", Decimal("0")) or Decimal("0")
    )
    remaining_quantity = (
        getattr(loan, "remaining_quantity_annotated", Decimal("0")) or Decimal("0")
    )
    item_count = int(getattr(loan, "item_count_annotated", 0) or 0)
    return {
        "pk": loan.pk,
        "reference": loan.reference,
        "status": loan.status,
        "status_display": loan.get_status_display(),
        "borrower": loan.borrower_display,
        "borrower_id": loan.borrower_id,
        "borrower_name": loan.borrower_display,
        "borrower_email": loan.borrower_email_display,
        "borrower_phone": loan.borrower_phone_display,
        "issued_by": str(loan.issued_by) if loan.issued_by else "",
        "issued_at": _iso(loan.issued_at),
        "due_at": _iso(loan.due_at),
        "returned_at": _iso(loan.returned_at),
        "is_overdue": loan.is_overdue,
        "days_overdue": loan.days_overdue,
        "renewals": loan.renewals,
        "notes": loan.notes,
        "item_count": item_count,
        "total_quantity": _num(total_quantity),
        "remaining_quantity": _num(remaining_quantity),
        "request_pk": loan.request_id,
        "request_reference": loan.request.reference if loan.request else "",
        "qr_url": reverse("plugin:loan:qr", args=[loan.pk]),
        "handout_receipt_url": reverse(
            "plugin:loan:receipt", args=[loan.pk]
        )
        + "?type=handout",
        "return_receipt_url": reverse(
            "plugin:loan:receipt", args=[loan.pk]
        )
        + "?type=return",
        "can_return": handout and loan.is_open,
        "can_renew": handout and loan.is_open,
        "can_mark_lost": handout and loan.is_open,
    }


def _filter_event_list(queryset, params):
    search = params.get("search", "").strip()
    if search:
        queryset = queryset.filter(
            Q(notes__icontains=search)
            | Q(actor__username__icontains=search)
            | Q(actor__first_name__icontains=search)
            | Q(actor__last_name__icontains=search)
            | Q(loan__reference__icontains=search)
            | Q(request__reference__icontains=search)
        ).distinct()
    event_type = params.get("event_type", "").strip()
    if event_type:
        queryset = queryset.filter(event_type=event_type)
    return queryset


def _filter_staff_list(queryset, params):
    search = params.get("search", "").strip()
    if search:
        queryset = queryset.filter(
            Q(user__username__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(user__email__icontains=search)
        )
    role = params.get("role", "").strip()
    if role:
        queryset = queryset.filter(role=role)
    active = params.get("active", "").strip().lower()
    if active in {"1", "true", "yes"}:
        queryset = queryset.filter(active=True)
    elif active in {"0", "false", "no"}:
        queryset = queryset.filter(active=False)
    return queryset


def _allocation_data(line) -> list[dict]:
    return [
        {
            "pk": allocation.pk,
            "stock_item": allocation.stock_item_id,
            "stock_item_label": str(allocation.stock_item),
            "stock_item_serial": allocation.stock_item.serial or "",
            "stock_item_url": _web_url(f"/stock/item/{allocation.stock_item_id}/"),
            "location": (
                allocation.stock_item.location.pathstring
                if allocation.stock_item.location
                else ""
            ),
            "quantity": _num(allocation.quantity),
        }
        for allocation in line.allocations.all()
    ]


def _drf_error(exc: DjangoValidationError):
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    if hasattr(exc, "messages"):
        return exc.messages
    return str(exc)


def _pickup_data(pickup: LoanPickup | None) -> dict | None:
    if pickup is None:
        return None
    return {
        "pk": pickup.pk,
        "reference": pickup.reference,
        "name": pickup.name,
        "display_name": pickup.display_name,
        "status": pickup.status,
        "status_display": pickup.get_status_display(),
        "token": str(pickup.token),
        "ready_at": _iso(pickup.ready_at),
        "collected_at": _iso(pickup.collected_at),
        "label_url": reverse("plugin:loan:pickup_label", args=[pickup.pk]),
        "return_sheet_url": reverse(
            "plugin:loan:pickup_return_sheet", args=[pickup.pk]
        ),
        "qr_url": reverse("plugin:loan:pickup_qr", args=[pickup.pk]),
    }


def _request_data(request: LoanRequest, user) -> dict:
    loan = getattr(request, "loan", None)
    lines = list(request.lines.all())
    availability = (
        part_availability_bulk(
            [line.part for line in lines], exclude_request=request
        )
        if lines
        else {}
    )
    approve = can_approve(user)
    handout = can_handout(user)
    total_quantity = sum((line.quantity for line in lines), Decimal("0"))
    approved_quantity = sum(
        (line.approved_quantity for line in lines), Decimal("0")
    )
    allocated_by_line = {
        line.pk: sum(
            (allocation.quantity for allocation in line.allocations.all()),
            Decimal("0"),
        )
        for line in lines
    }
    return {
        "pk": request.pk,
        "reference": request.reference,
        "status": request.status,
        "status_display": request.get_status_display(),
        "requester": request.requester_display,
        "requester_id": request.requester_id,
        "requester_name": request.requester_display,
        "requester_email": request.requester_email_display,
        "signature": request.signature,
        "public_token": str(request.public_token),
        "track_url": (
            reverse("plugin:loan:public_request_detail", args=[request.public_token])
            if request.requester_id is None
            else ""
        ),
        "request_url": _web_url(f"/plugin/loan/requests/{request.pk}"),
        "purpose": request.purpose,
        "needed_by": _iso(request.needed_by),
        "return_by": _iso(request.return_by),
        "notes": request.notes,
        "decision_notes": request.decision_notes,
        "custom_fields": custom_field_values(request),
        "decided_by": str(request.decided_by) if request.decided_by else "",
        "decided_at": _iso(request.decided_at),
        "created": _iso(request.created),
        "item_count": len(lines),
        "total_quantity": _num(total_quantity),
        "approved_quantity": _num(approved_quantity),
        "is_fully_approved": all(
            line.approved_quantity >= line.quantity for line in lines
        ),
        "is_fully_allocated": all(
            allocated_by_line.get(line.pk, Decimal("0"))
            >= line.approved_quantity
            for line in lines
        ),
        "loan_pk": loan.pk if loan else None,
        "loan_reference": loan.reference if loan else "",
        "loan_status": loan.status if loan else "",
        "loan_status_display": loan.get_status_display() if loan else "",
        "loan_returned_at": _iso(loan.returned_at) if loan else None,
        "pickup": _pickup_data(getattr(request, "pickup", None)),
        "can_approve": approve
        and request.status in {"pending", "partially_approved"},
        "can_handout": handout,
        "can_mark_ready": approve
        and request.status
        in {"approved", "partially_approved", "ready_for_pickup"},
        "can_cancel": request.status
        in {
            "pending",
            "approved",
            "partially_approved",
            "ready_for_pickup",
            "partially_fulfilled",
        },
        "can_checkout": handout
        and (
            request.status
            in {"approved", "partially_approved", "ready_for_pickup"}
            or (request.status == "pending" and not get_setting("REQUIRE_APPROVAL", True))
        ),
        "lines": [
            {
                "pk": line.pk,
                "part": line.part_id,
                "part_name": line.part.name,
                "ipn": line.part.IPN or "",
                "part_url": _web_url(f"/part/{line.part_id}/"),
                "stock_item": line.stock_item_id,
                "stock_item_label": str(line.stock_item) if line.stock_item else "",
                "stock_item_url": (
                    _web_url(f"/stock/item/{line.stock_item_id}/")
                    if line.stock_item_id
                    else ""
                ),
                "quantity": _num(line.quantity),
                "approved_quantity": _num(line.approved_quantity),
                "notes": line.notes,
                "allocations": _allocation_data(line),
                "allocated_quantity": _num(
                    allocated_by_line.get(line.pk, Decimal("0"))
                ),
                "unallocated_quantity": _num(
                    max(
                        line.approved_quantity
                        - allocated_by_line.get(line.pk, Decimal("0")),
                        Decimal("0"),
                    )
                ),
                "is_fully_allocated": allocated_by_line.get(
                    line.pk, Decimal("0")
                )
                >= line.approved_quantity,
                "available_stock": _num(
                    availability.get(line.part_id, {}).get(
                        "available", Decimal("0")
                    )
                ),
            }
            for line in lines
        ],
        "url": reverse("plugin:loan:request_detail", args=[request.pk]),
    }


def _loan_data(loan: Loan, user, include_events: bool = False) -> dict:
    handout = can_handout(user)
    items = list(loan.items.all())
    total_quantity = sum((item.quantity for item in items), Decimal("0"))
    remaining_quantity = sum(
        (item.remaining_quantity for item in items), Decimal("0")
    )
    data = {
        "pk": loan.pk,
        "reference": loan.reference,
        "status": loan.status,
        "status_display": loan.get_status_display(),
        "borrower": loan.borrower_display,
        "borrower_id": loan.borrower_id,
        "borrower_name": loan.borrower_display,
        "borrower_email": loan.borrower_email_display,
        "borrower_phone": loan.borrower_phone_display,
        "issued_by": str(loan.issued_by) if loan.issued_by else "",
        "issued_at": _iso(loan.issued_at),
        "due_at": _iso(loan.due_at),
        "returned_at": _iso(loan.returned_at),
        "signature_checkout": loan.signature_checkout,
        "signature_checkout_at": _iso(loan.signature_checkout_at),
        "signature_return": loan.signature_return,
        "signature_return_at": _iso(loan.signature_return_at),
        "is_overdue": loan.is_overdue,
        "days_overdue": loan.days_overdue,
        "renewals": loan.renewals,
        "notes": loan.notes,
        "item_count": len(items),
        "total_quantity": _num(total_quantity),
        "remaining_quantity": _num(remaining_quantity),
        "qr_url": reverse("plugin:loan:qr", args=[loan.pk]),
        "receipt_url": reverse("plugin:loan:receipt", args=[loan.pk]),
        "can_return": handout and loan.is_open,
        "can_renew": handout and loan.is_open,
        "can_mark_lost": handout and loan.is_open,
        "items": [
            {
                "pk": item.pk,
                "part": item.part_id,
                "part_name": item.part.name,
                "ipn": item.part.IPN or "",
                "stock_item": item.stock_item_id,
                "stock_item_label": item.stock_item_display,
                "quantity": _num(item.quantity),
                "returned_quantity": _num(item.returned_quantity),
                "remaining_quantity": _num(item.remaining_quantity),
                "condition_on_issue": item.condition_on_issue,
                "condition_on_return": item.condition_on_return,
                "returned_at": _iso(item.returned_at),
                "lost": item.lost,
                "notes": item.return_notes,
                "original_location": str(item.original_location) if item.original_location else "",
            }
            for item in items
        ],
    }
    if include_events:
        data["events"] = [
            {
                "event_type": event.get_event_type_display(),
                "actor": event.actor_name,
                "notes": event.notes,
                "created": _iso(event.created),
            }
            for event in loan.events.all()[:100]
        ]
    return data


def _public_request_data(loan_request: LoanRequest) -> dict:
    """Return the safe subset of request data exposed through a tracking token."""
    loan = Loan.objects.filter(request=loan_request).first()
    return {
        "reference": loan_request.reference,
        "status": loan_request.status,
        "status_display": loan_request.get_status_display(),
        "requester_name": loan_request.requester_display,
        "requester_email": loan_request.requester_email_display,
        "purpose": loan_request.purpose,
        "needed_by": _iso(loan_request.needed_by),
        "return_by": _iso(loan_request.return_by),
        "notes": loan_request.notes,
        "decision_notes": loan_request.decision_notes,
        "custom_fields": custom_field_values(loan_request),
        "created": _iso(loan_request.created),
        "has_signature": bool(loan_request.signature),
        "public_token": str(loan_request.public_token),
        "track_url": reverse(
            "plugin:loan:public_request_detail", args=[loan_request.public_token]
        ),
        "receipt_url": reverse(
            "plugin:loan:public_request_receipt", args=[loan_request.public_token]
        ),
        "lines": [
            {
                "pk": line.pk,
                "part_name": line.part.name,
                "ipn": line.part.IPN or "",
                "stock_item_label": str(line.stock_item) if line.stock_item else "",
                "quantity": _num(line.quantity),
                "approved_quantity": _num(line.approved_quantity),
                "notes": line.notes,
            }
            for line in loan_request.lines.all()
        ],
        "loan": (
            {
                "reference": loan.reference,
                "status": loan.status,
                "status_display": loan.get_status_display(),
                "due_at": _iso(loan.due_at),
                "returned_at": _iso(loan.returned_at),
                "has_checkout_signature": bool(loan.signature_checkout),
                "has_return_signature": bool(loan.signature_return),
            }
            if loan
            else None
        ),
    }


class LoanAPIView(APIView):
    """Base API view with session/DRF authentication."""

    permission_classes = [IsAuthenticated]


class PublicCatalogCategoriesView(APIView):
    """Anonymous category browser for the public request page."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        return Response({"results": catalog_categories()})


class PublicCatalogView(APIView):
    """Anonymous part catalog for the public request page."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        search = request.GET.get("search", "").strip()
        category_id = request.GET.get("category")
        try:
            category_id = int(category_id) if category_id else None
        except (TypeError, ValueError):
            category_id = None
        limit = int(request.GET.get("limit", get_setting("CATALOG_PAGE_SIZE", 20) or 20))
        try:
            offset = max(int(request.GET.get("offset", 0)), 0)
        except (TypeError, ValueError):
            offset = 0
        return Response(
            catalog_parts(
                search,
                limit=min(max(limit, 1), 100),
                category_id=category_id,
                offset=offset,
            )
        )


class PublicPartDetailView(APIView):
    """Anonymous part detail used by the public catalogue."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request, pk):
        data = part_detail(pk, include_stock_items=False)
        if data is None:
            raise Http404
        return Response(data)


class PublicPartImageView(APIView):
    """Serve a part image without requiring an InvenTree session."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request, pk):
        import mimetypes
        from pathlib import Path

        from django.http import FileResponse

        from part.models import Part

        from ..config import get_loanable_category

        part = get_object_or_404(Part, pk=pk, active=True, virtual=False)
        base = get_loanable_category()
        if base and (
            not part.category
            or not (
                part.category.pathstring == base.pathstring
                or part.category.pathstring.startswith(f"{base.pathstring}/")
            )
        ):
            raise Http404
        try:
            path = Path(part.image.path)
        except Exception:
            raise Http404
        if not path.is_file():
            raise Http404
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        response = FileResponse(path.open("rb"), content_type=content_type)
        response["Cache-Control"] = "private, max-age=3600"
        return response


class PublicScanView(APIView):
    """Resolve a barcode for the public catalogue without exposing loan data."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        serializer = ScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = resolve_barcode(None, serializer.validated_data["barcode"])
        if result.get("type") == "stockitem":
            # Public requesters request parts, never a specific stock item.
            data = result.get("data") or {}
            return Response(
                {
                    "success": True,
                    "type": "part",
                    "data": {
                        "pk": data.get("part"),
                        "name": data.get("part_name"),
                        "ipn": data.get("ipn", ""),
                        "trackable": bool(data.get("trackable")),
                    },
                }
            )
        if result.get("type") in {"loan", "stocklocation"}:
            return Response(
                {
                    "success": False,
                    "error": "Scan a part barcode to add it to the request.",
                }
            )
        return Response(result)


@method_decorator(csrf_protect, name="dispatch")
class PublicRequestCreateView(APIView):
    """Create a loan request without requiring an InvenTree account."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        if not get_setting("ALLOW_ANONYMOUS_REQUESTS", True):
            raise PermissionDenied("Public loan requests are disabled")
        serializer = PublicRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            loan_request = create_request(
                None,
                data["lines"],
                purpose=data.get("purpose", ""),
                needed_by=data.get("needed_by"),
                return_by=data.get("return_by"),
                notes=data.get("notes", ""),
                responsibility_ack=data.get("responsibility_ack", False),
                requester_name=data.get("requester_name", ""),
                requester_email=data.get("requester_email", ""),
                signature=data.get("signature", ""),
                allow_anonymous=True,
                require_signature=True,
                purpose_required=get_public_field_config().get("purpose")
                == "required",
                custom_fields=data.get("custom_fields", {}),
            )
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(
            _public_request_data(loan_request), status=status.HTTP_201_CREATED
        )


class PublicRequestDetailView(APIView):
    """Track a request through its secret public token."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request, token):
        loan_request = get_object_or_404(
            LoanRequest.objects.select_related("requester")
            .prefetch_related("lines__part", "lines__stock_item"),
            public_token=token,
        )
        return Response(_public_request_data(loan_request))


@method_decorator(csrf_protect, name="dispatch")
class PublicRequestLookupView(APIView):
    """Find an anonymous request using its reference and email address."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = PublicRequestLookupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reference = serializer.validated_data["reference"].strip()
        email = serializer.validated_data["email"].strip().lower()
        loan_request = (
            LoanRequest.objects.select_related("requester")
            .prefetch_related("lines__part", "lines__stock_item")
            .filter(reference__iexact=reference)
            .first()
        )
        if loan_request is None or (
            loan_request.requester_email_display or ""
        ).strip().lower() != email:
            raise Http404
        return Response(_public_request_data(loan_request))


class PublicRequestQRCodeView(APIView):
    """Return a QR code for a request's public tracking page."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request, token):
        loan_request = get_object_or_404(LoanRequest, public_token=token)
        url = request.build_absolute_uri(
            reverse("plugin:loan:public_request_detail", args=[token])
        )
        response = HttpResponse(
            generate_qr_svg_payload(url), content_type="image/svg+xml"
        )
        response["Cache-Control"] = "private, max-age=3600"
        return response


class CatalogView(LoanAPIView):
    """Search the requester-safe part catalog."""

    def get(self, request):
        search = request.GET.get("search", "").strip()
        limit = int(request.GET.get("limit", get_setting("CATALOG_PAGE_SIZE", 20) or 20))
        return Response(catalog_parts(search, limit=min(max(limit, 1), 100)))


class RequestListCreateView(LoanAPIView):
    """List visible requests, or create a new request."""

    def get(self, request):
        limit, offset = _page_params(request)
        queryset = _request_sort(
            _filter_request_list(
                _request_list_queryset(request.user),
                request.GET,
            ),
            request.GET,
        )
        total = queryset.count()
        require_approval = bool(get_setting("REQUIRE_APPROVAL", True))
        permissions = _list_permissions(request.user)
        page = queryset[offset : offset + limit]
        return Response(
            {
                "results": [
                    _request_summary_data(
                        item, request.user, require_approval, permissions
                    )
                    for item in page
                ],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    def post(self, request):
        if not can_request(request.user):
            raise PermissionDenied("You do not have permission to request loans")
        serializer = RequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            loan_request = create_request(
                request.user,
                data["lines"],
                purpose=data.get("purpose", ""),
                needed_by=data.get("needed_by"),
                return_by=data.get("return_by"),
                notes=data.get("notes", ""),
                responsibility_ack=data.get("responsibility_ack", False),
                requester_name=data.get("requester_name", ""),
                requester_email=data.get("requester_email", ""),
                signature=data.get("signature", ""),
            )
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(_request_data(loan_request, request.user), status=status.HTTP_201_CREATED)


class RequestDetailView(LoanAPIView):
    """Retrieve a visible request."""

    def get(self, request, pk):
        loan_request = request_with_lines(request.user, pk)
        if loan_request is None:
            raise Http404
        data = _request_data(loan_request, request.user)
        data["events"] = [
            {
                "event_type": event.get_event_type_display(),
                "actor": event.actor_name,
                "notes": event.notes,
                "created": _iso(event.created),
            }
            for event in loan_request.events.all()[:100]
        ]
        return Response(data)


class RequestDecisionView(LoanAPIView):
    """Approve or reject a request."""

    action = "approve"
    serializer_class = DecisionSerializer

    def post(self, request, pk):
        loan_request = get_object_or_404(visible_requests(request.user), pk=pk)
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            if self.action == "approve":
                approvals = None
                if "lines" in data:
                    approvals = {
                        entry["line_id"]: entry["quantity"]
                        for entry in data["lines"]
                    }
                loan_request = approve_request(
                    loan_request,
                    request.user,
                    data.get("notes", ""),
                    approvals=approvals,
                )
            else:
                loan_request = reject_request(
                    loan_request, request.user, data.get("notes", "")
                )
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(_request_data(loan_request, request.user))


class RequestApproveView(RequestDecisionView):
    action = "approve"
    serializer_class = ApproveSerializer


class RequestRejectView(RequestDecisionView):
    action = "reject"
    serializer_class = DecisionSerializer


class RequestCancelView(LoanAPIView):
    """Cancel a request."""

    def post(self, request, pk):
        loan_request = get_object_or_404(visible_requests(request.user), pk=pk)
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            loan_request = cancel_request(
                loan_request, request.user, serializer.validated_data["notes"]
            )
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(_request_data(loan_request, request.user))


class RequestReadyView(LoanAPIView):
    """Pack an approved request and mark it ready for pickup."""

    def post(self, request, pk):
        loan_request = get_object_or_404(visible_requests(request.user), pk=pk)
        serializer = ReadyForPickupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            mark_ready_for_pickup(
                loan_request,
                request.user,
                name=data.get("name", ""),
                notes=data.get("notes", ""),
            )
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(
            _request_data(request_with_lines(request.user, pk), request.user)
        )


class RequestAllocateView(LoanAPIView):
    """Auto-allocate a request or add/clear a manual allocation."""

    def post(self, request, pk):
        loan_request = get_object_or_404(visible_requests(request.user), pk=pk)
        serializer = RequestAllocateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            if data.get("clear"):
                clear_allocations(loan_request, request.user)
            elif data.get("auto"):
                auto_allocate_request(loan_request, request.user)
            else:
                add_allocation(
                    loan_request,
                    request.user,
                    line_id=data["line_id"],
                    stock_item_id=data["stock_item_id"],
                    quantity=data.get("quantity", 1),
                )
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(
            _request_data(request_with_lines(request.user, pk), request.user)
        )


class RequestAllocationCandidatesView(LoanAPIView):
    """Return stock items which can be allocated to a request line."""

    def get(self, request, pk):
        loan_request = get_object_or_404(visible_requests(request.user), pk=pk)
        line_id = request.GET.get("line_id")
        line = loan_request.lines.filter(pk=line_id).select_related("part").first()
        if line is None:
            raise Http404
        data = part_detail(line.part_id, exclude_request=loan_request)
        if data is None:
            raise Http404
        stock_items = data["stock_items"]
        if line.stock_item_id:
            stock_items = [
                item for item in stock_items if item["pk"] == line.stock_item_id
            ]
        return Response({
            "line_id": line.pk,
            "part": line.part_id,
            "part_name": line.part.name,
            "requested": _num(line.quantity),
            "allocated": _num(line.allocated_quantity),
            "outstanding": _num(line.unallocated_quantity),
            "stock_items": stock_items,
        })


class RequestAllocationDeleteView(LoanAPIView):
    """Remove one allocation from a request."""

    def delete(self, request, pk, allocation_pk):
        loan_request = get_object_or_404(visible_requests(request.user), pk=pk)
        try:
            remove_allocation(loan_request, request.user, allocation_pk)
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(
            _request_data(request_with_lines(request.user, pk), request.user)
        )


class LoanListView(LoanAPIView):
    """List visible loans."""

    def get(self, request):
        limit, offset = _page_params(request)
        queryset = _loan_sort(
            _filter_loan_list(
                _loan_list_queryset(request.user),
                request.GET,
            ),
            request.GET,
        )
        total = queryset.count()
        permissions = _list_permissions(request.user)
        page = queryset[offset : offset + limit]
        return Response(
            {
                "results": [
                    _loan_summary_data(item, request.user, permissions)
                    for item in page
                ],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )


class LoanDetailView(LoanAPIView):
    """Retrieve a visible loan."""

    def get(self, request, pk):
        loan = loan_with_items(request.user, pk)
        if loan is None:
            raise Http404
        return Response(_loan_data(loan, request.user, include_events=True))


class CheckoutView(LoanAPIView):
    """Issue an approved request or a walk-in loan."""

    def post(self, request):
        if not can_handout(request.user):
            raise PermissionDenied("You do not have permission to issue loans")
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            if data.get("request_id"):
                loan_request = get_object_or_404(
                    visible_requests(request.user), pk=data["request_id"]
                )
                loan = checkout_request(
                    loan_request,
                    request.user,
                    due_at=data.get("due_at"),
                    notes=data.get("notes", ""),
                    allow_pending=not get_setting("REQUIRE_APPROVAL", True),
                    signature=data.get("signature", ""),
                )
            else:
                borrower = get_object_or_404(
                    get_user_model(), pk=data["borrower_id"], is_active=True
                )
                loan = checkout_direct(
                    request.user,
                    borrower,
                    data.get("items", []),
                    due_at=data.get("due_at"),
                    notes=data.get("notes", ""),
                    signature=data.get("signature", ""),
                )
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(_loan_data(loan, request.user), status=status.HTTP_201_CREATED)


class LoanReturnView(LoanAPIView):
    """Return all or part of a loan."""

    def post(self, request, pk):
        loan = get_object_or_404(visible_loans(request.user), pk=pk)
        serializer = ReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lines = serializer.validated_data.get("lines") or []
        if not lines:
            lines = [
                {"item_id": item.pk, "quantity": item.remaining_quantity}
                for item in loan.items.all()
                if item.is_open
            ]
        try:
            return_loan(
                loan,
                request.user,
                lines,
                signature=serializer.validated_data.get("signature", ""),
            )
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(_loan_data(loan_with_items(request.user, pk), request.user, include_events=True))


class LoanRenewView(LoanAPIView):
    """Extend a loan's due date."""

    def post(self, request, pk):
        loan = get_object_or_404(visible_loans(request.user), pk=pk)
        serializer = RenewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            renew_loan(
                loan,
                request.user,
                serializer.validated_data["due_at"],
                serializer.validated_data.get("notes", ""),
            )
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(_loan_data(loan_with_items(request.user, pk), request.user))


class LoanItemLostView(LoanAPIView):
    """Mark an item on a loan as lost."""

    def post(self, request, pk, item_pk):
        loan = get_object_or_404(visible_loans(request.user), pk=pk)
        item = get_object_or_404(LoanItem, pk=item_pk, loan=loan)
        serializer = LostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            mark_lost(item, request.user, serializer.validated_data.get("notes", ""))
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(_loan_data(loan_with_items(request.user, pk), request.user))


class ScanView(LoanAPIView):
    """Resolve a barcode or loan QR code."""

    def post(self, request):
        serializer = ScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(resolve_barcode(request.user, serializer.validated_data["barcode"]))


def _setup_data() -> dict:
    location = get_loan_location()
    status = get_on_loan_status()
    return {
        "configured": is_configured(),
        "location": getattr(location, "pathstring", ""),
        "location_id": getattr(location, "pk", None),
        "status": getattr(status, "label", ""),
        "status_key": getattr(status, "key", None),
        "status_logical_key": getattr(status, "logical_key", None),
    }


class SetupView(LoanAPIView):
    """Read or repair the loan stock configuration."""

    def get(self, request):
        if not can_manage_staff(request.user):
            raise PermissionDenied("You do not have permission to configure loans")
        return Response(_setup_data())

    def post(self, request):
        if not can_manage_staff(request.user):
            raise PermissionDenied("You do not have permission to configure loans")
        try:
            ensure_setup(create_location=True)
        except Exception as exc:
            raise ValidationError(str(exc)) from None
        return Response(_setup_data())


class EventListView(LoanAPIView):
    """Recent audit events for the admin console."""

    def get(self, request):
        if not can_view_all(request.user):
            raise PermissionDenied("You do not have permission to view history")
        limit, offset = _page_params(request, default_limit=50)
        queryset = _filter_event_list(
            visible_events(request.user), request.GET
        ).order_by("-created", "-pk")
        total = queryset.count()
        page = queryset[offset : offset + limit]
        return Response({
            "results": [
                {
                    "pk": event.pk,
                    "event_type": event.event_type,
                    "event_label": event.get_event_type_display(),
                    "actor": event.actor_name,
                    "notes": event.notes,
                    "created": _iso(event.created),
                    "loan_reference": event.loan.reference if event.loan else "",
                    "request_reference": event.request.reference if event.request else "",
                }
                for event in page
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        })


class StatsView(LoanAPIView):
    """Dashboard counters for the current user."""

    def get(self, request):
        now = timezone.now()
        visible_loans_qs = visible_loans(request.user)
        visible_requests_qs = visible_requests(request.user)
        due_soon_days = int(get_setting("DUE_SOON_DAYS", 2) or 2)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        return Response({
            "pending_requests": visible_requests_qs.filter(status="pending").count(),
            "approved_requests": visible_requests_qs.filter(status="approved").count(),
            "partially_approved_requests": visible_requests_qs.filter(
                status="partially_approved"
            ).count(),
            "ready_for_pickup_requests": visible_requests_qs.filter(
                status="ready_for_pickup"
            ).count(),
            "active_loans": visible_loans_qs.filter(
                status__in=["active", "partially_returned", "overdue"]
            ).count(),
            "overdue_loans": visible_loans_qs.filter(
                status__in=["active", "partially_returned", "overdue"], due_at__lt=now
            ).count(),
            "due_soon_loans": visible_loans_qs.filter(
                status__in=["active", "partially_returned"],
                due_at__gte=now,
                due_at__lte=now + timedelta(days=due_soon_days),
            ).count(),
            "returned_this_month": visible_loans_qs.filter(
                status="returned", returned_at__gte=month_start
            ).count(),
            "is_manager": can_view_all(request.user),
            "can_approve": can_approve(request.user),
            "can_handout": can_handout(request.user),
            "can_manage_staff": can_manage_staff(request.user),
            "can_request": can_request(request.user),
            "role": get_user_role(request.user),
            "public_request_url": get_public_request_url(),
        })


class QRCodeView(LoanAPIView):
    """Return a loan QR code as SVG."""

    def get(self, request, pk):
        loan = get_object_or_404(visible_loans(request.user), pk=pk)
        response = HttpResponse(generate_qr_svg(loan), content_type="image/svg+xml")
        response["Cache-Control"] = "private, max-age=3600"
        return response


class UserSearchView(LoanAPIView):
    """Search users for the loan desk."""

    def get(self, request):
        if not can_handout(request.user):
            raise PermissionDenied("You do not have permission to search users")
        search = request.GET.get("search", "").strip()
        if len(search) < 2:
            return Response({"results": []})
        User = get_user_model()
        users = (
            User.objects.filter(
                Q(username__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search),
                is_active=True,
            )
            .order_by("username")[:20]
        )
        return Response({
            "results": [
                {
                    "pk": user.pk,
                    "username": user.username,
                    "name": user.get_full_name() or user.username,
                    "email": user.email,
                }
                for user in users
            ]
        })


class StaffListCreateView(LoanAPIView):
    """List or grant loan staff roles."""

    def get(self, request):
        if not can_manage_staff(request.user):
            raise PermissionDenied("You do not have permission to manage loan staff")
        limit, offset = _page_params(request, default_limit=50)
        queryset = _filter_staff_list(
            LoanStaff.objects.select_related("user", "created_by").order_by(
                "user__username"
            ),
            request.GET,
        )
        total = queryset.count()
        page = queryset[offset : offset + limit]
        return Response({
            "results": [
                {
                    "pk": item.pk,
                    "user_id": item.user_id,
                    "username": item.user.username,
                    "name": item.user.get_full_name() or item.user.username,
                    "role": item.role,
                    "role_display": item.get_role_display(),
                    "active": item.active,
                    "created_by": str(item.created_by) if item.created_by else "",
                }
                for item in page
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        })

    def post(self, request):
        if not can_manage_staff(request.user):
            raise PermissionDenied("You do not have permission to manage loan staff")
        serializer = StaffCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        User = get_user_model()
        if data.get("user_id"):
            user = get_object_or_404(User, pk=data["user_id"])
        else:
            user = get_object_or_404(User, username=data["username"])
        role = data["role"]
        existing = LoanStaff.objects.filter(user=user).first()
        if (
            role == LoanStaffRole.ADMIN
            and not request.user.is_superuser
            and not (existing and existing.role == LoanStaffRole.ADMIN)
        ):
            raise PermissionDenied("Only a superuser can grant Loan Administrator")

        if (
            existing
            and existing.role == LoanStaffRole.ADMIN
            and existing.active
            and (role != LoanStaffRole.ADMIN or not data.get("active", True))
        ):
            if not request.user.is_superuser and LoanStaff.objects.filter(
                role=LoanStaffRole.ADMIN, active=True
            ).exclude(pk=existing.pk).count() == 0:
                raise ValidationError("The last active Loan Administrator cannot be demoted")

        staff, created = LoanStaff.objects.update_or_create(
            user=user,
            defaults={
                "role": role,
                "active": data.get("active", True),
                "created_by": request.user,
            },
        )
        LoanEvent.record(
            event_type="staff_added" if created else "updated",
            actor=request.user,
            notes=f"{user} -> {staff.get_role_display()}",
        )
        return Response({"pk": staff.pk, "created": created}, status=201 if created else 200)


class StaffDetailView(LoanAPIView):
    """Update or remove a staff role."""

    def patch(self, request, pk):
        if not can_manage_staff(request.user):
            raise PermissionDenied("You do not have permission to manage loan staff")
        staff = get_object_or_404(LoanStaff, pk=pk)
        serializer = StaffUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        new_role = data.get("role", staff.role)
        new_active = data.get("active", staff.active)
        if (
            new_role == LoanStaffRole.ADMIN
            and not request.user.is_superuser
            and staff.role != LoanStaffRole.ADMIN
        ):
            raise PermissionDenied("Only a superuser can grant Loan Administrator")
        if staff.role == LoanStaffRole.ADMIN and (new_role != LoanStaffRole.ADMIN or not new_active):
            if not request.user.is_superuser and LoanStaff.objects.filter(
                role=LoanStaffRole.ADMIN, active=True
            ).exclude(pk=staff.pk).count() == 0:
                raise ValidationError("The last active Loan Administrator cannot be demoted")
        staff.role = new_role
        staff.active = new_active
        staff.save(update_fields=["role", "active", "updated"])
        LoanEvent.record(
            event_type="updated",
            actor=request.user,
            notes=f"{staff.user} -> {staff.get_role_display()} (active={staff.active})",
        )
        return Response({"pk": staff.pk})

    def delete(self, request, pk):
        if not can_manage_staff(request.user):
            raise PermissionDenied("You do not have permission to manage loan staff")
        staff = get_object_or_404(LoanStaff, pk=pk)
        if staff.role == LoanStaffRole.ADMIN and staff.active:
            if not request.user.is_superuser and LoanStaff.objects.filter(
                role=LoanStaffRole.ADMIN, active=True
            ).exclude(pk=staff.pk).count() == 0:
                raise ValidationError("The last active Loan Administrator cannot be removed")
        user = staff.user
        staff.delete()
        LoanEvent.record(
            event_type="staff_removed",
            actor=request.user,
            notes=f"Removed {user}",
        )
        return Response(status=204)


class CustomFieldListView(LoanAPIView):
    """List or create public form field definitions."""

    def get(self, request):
        if not can_manage_staff(request.user):
            raise PermissionDenied(
                "You do not have permission to manage public form fields"
            )
        fields = LoanRequestCustomField.objects.all()
        return Response(
            {"results": CustomFieldSerializer(fields, many=True).data}
        )

    def post(self, request):
        if not can_manage_staff(request.user):
            raise PermissionDenied(
                "You do not have permission to manage public form fields"
            )
        serializer = CustomFieldSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        field = serializer.save()
        return Response(
            CustomFieldSerializer(field).data, status=status.HTTP_201_CREATED
        )


class CustomFieldDetailView(LoanAPIView):
    """Update or archive a public form field."""

    def patch(self, request, pk):
        if not can_manage_staff(request.user):
            raise PermissionDenied(
                "You do not have permission to manage public form fields"
            )
        field = get_object_or_404(LoanRequestCustomField, pk=pk)
        serializer = CustomFieldSerializer(
            field, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        field = serializer.save()
        return Response(CustomFieldSerializer(field).data)

    def delete(self, request, pk):
        if not can_manage_staff(request.user):
            raise PermissionDenied(
                "You do not have permission to manage public form fields"
            )
        field = get_object_or_404(LoanRequestCustomField, pk=pk)
        field.active = False
        field.save(update_fields=["active", "updated"])
        return Response(status=status.HTTP_204_NO_CONTENT)


def _csv_safe(value):
    if value is None:
        return ""
    value = str(value)
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


class ExportRequestsView(LoanAPIView):
    """Export visible requests as CSV."""

    def get(self, request):
        output = io.StringIO()
        writer = csv.writer(output)
        custom_fields = list(LoanRequestCustomField.objects.all())
        writer.writerow([
            "Reference", "Requester", "Status", "Purpose", "Pickup", "Return",
            "Items", "Created", "Decided by", "Decision notes",
            *[field.label for field in custom_fields],
        ])
        queryset = _request_sort(
            _filter_request_list(
                _request_list_queryset(request.user), request.GET
            ),
            request.GET,
        )[:5000]
        for item in queryset:
            writer.writerow([
                _csv_safe(item.reference),
                _csv_safe(item.requester_display),
                _csv_safe(item.get_status_display()),
                _csv_safe(item.purpose),
                _csv_safe(item.needed_by),
                _csv_safe(item.return_by),
                _csv_safe(getattr(item, "item_count_annotated", 0)),
                _csv_safe(item.created.isoformat() if item.created else ""),
                _csv_safe(item.decided_by),
                _csv_safe(item.decision_notes),
                *[
                    _csv_safe(
                        "Yes" if field.field_type == "checkbox" and item.custom_fields.get(field.key)
                        else "No" if field.field_type == "checkbox"
                        else item.custom_fields.get(field.key, "")
                    )
                    for field in custom_fields
                ],
            ])
        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="loan-requests.csv"'
        return response


class ExportLoansView(LoanAPIView):
    """Export visible loans as CSV."""

    def get(self, request):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Reference", "Borrower", "Status", "Issued", "Due", "Returned",
            "Items", "Renewals", "Notes",
        ])
        queryset = _loan_sort(
            _filter_loan_list(
                _loan_list_queryset(request.user), request.GET
            ),
            request.GET,
        )[:5000]
        for loan in queryset:
            writer.writerow([
                _csv_safe(loan.reference),
                _csv_safe(loan.borrower_display),
                _csv_safe(loan.get_status_display()),
                _csv_safe(loan.issued_at.isoformat() if loan.issued_at else ""),
                _csv_safe(loan.due_at.isoformat() if loan.due_at else ""),
                _csv_safe(loan.returned_at.isoformat() if loan.returned_at else ""),
                _csv_safe(getattr(loan, "item_count_annotated", 0)),
                _csv_safe(loan.renewals),
                _csv_safe(loan.notes),
            ])
        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="loans.csv"'
        return response
