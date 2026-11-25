"""JSON API for the loan plugin."""

from __future__ import annotations

import csv
import io
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..config import get_setting
from ..models import (
    Loan,
    LoanEvent,
    LoanItem,
    LoanRequest,
    LoanStaff,
    LoanStaffRole,
)
from ..permissions import (
    can_approve,
    can_handout,
    can_manage_staff,
    can_request,
    can_view_all,
)
from ..selectors import (
    loan_with_items,
    request_with_lines,
    visible_loans,
    visible_requests,
)
from ..services.barcode import generate_qr_svg, resolve_barcode
from ..services.checkout import checkout_direct, checkout_request
from ..services.requests import (
    approve_request,
    cancel_request,
    catalog_parts,
    create_request,
    reject_request,
)
from ..services.returns import mark_lost, renew_loan, return_loan
from .serializers import (
    CheckoutSerializer,
    DecisionSerializer,
    LostSerializer,
    RenewSerializer,
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


def _drf_error(exc: DjangoValidationError):
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    if hasattr(exc, "messages"):
        return exc.messages
    return str(exc)


def _request_data(request: LoanRequest, user) -> dict:
    return {
        "pk": request.pk,
        "reference": request.reference,
        "status": request.status,
        "status_display": request.get_status_display(),
        "requester": str(request.requester),
        "requester_id": request.requester_id,
        "purpose": request.purpose,
        "needed_by": _iso(request.needed_by),
        "return_by": _iso(request.return_by),
        "notes": request.notes,
        "contact": request.contact,
        "project": request.project,
        "decision_notes": request.decision_notes,
        "decided_by": str(request.decided_by) if request.decided_by else "",
        "decided_at": _iso(request.decided_at),
        "created": _iso(request.created),
        "item_count": request.item_count,
        "total_quantity": _num(request.total_quantity),
        "can_approve": can_approve(user) and request.status == "pending",
        "can_cancel": request.status in {"pending", "approved", "partially_fulfilled"},
        "can_checkout": can_handout(user)
        and (
            request.status == "approved"
            or (request.status == "pending" and not get_setting("REQUIRE_APPROVAL", True))
        ),
        "lines": [
            {
                "pk": line.pk,
                "part": line.part_id,
                "part_name": line.part.name,
                "ipn": line.part.IPN or "",
                "stock_item": line.stock_item_id,
                "stock_item_label": str(line.stock_item) if line.stock_item else "",
                "quantity": _num(line.quantity),
                "notes": line.notes,
            }
            for line in request.lines.all()
        ],
        "url": reverse("plugin:loan:request_detail", args=[request.pk]),
    }


def _loan_data(loan: Loan, user, include_events: bool = False) -> dict:
    data = {
        "pk": loan.pk,
        "reference": loan.reference,
        "status": loan.status,
        "status_display": loan.get_status_display(),
        "borrower": str(loan.borrower),
        "borrower_id": loan.borrower_id,
        "issued_by": str(loan.issued_by),
        "issued_at": _iso(loan.issued_at),
        "due_at": _iso(loan.due_at),
        "returned_at": _iso(loan.returned_at),
        "is_overdue": loan.is_overdue,
        "days_overdue": loan.days_overdue,
        "renewals": loan.renewals,
        "notes": loan.notes,
        "item_count": loan.item_count,
        "total_quantity": _num(loan.total_quantity),
        "remaining_quantity": _num(loan.remaining_quantity),
        "qr_url": reverse("plugin:loan:qr", args=[loan.pk]),
        "receipt_url": reverse("plugin:loan:receipt", args=[loan.pk]),
        "can_return": can_handout(user) and loan.is_open,
        "can_renew": can_handout(user) and loan.is_open,
        "can_mark_lost": can_handout(user) and loan.is_open,
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
            for item in loan.items.all()
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


class LoanAPIView(APIView):
    """Base API view with session/DRF authentication."""

    permission_classes = [IsAuthenticated]


class CatalogView(LoanAPIView):
    """Search the requester-safe part catalog."""

    def get(self, request):
        search = request.GET.get("search", "").strip()
        limit = int(request.GET.get("limit", get_setting("CATALOG_PAGE_SIZE", 20) or 20))
        return Response({"results": catalog_parts(search, limit=min(max(limit, 1), 100))})


class RequestListCreateView(LoanAPIView):
    """List visible requests, or create a new request."""

    def get(self, request):
        queryset = visible_requests(request.user)
        status_filter = request.GET.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return Response({"results": [_request_data(req, request.user) for req in queryset[:200]]})

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
                contact=data.get("contact", ""),
                project=data.get("project", ""),
                responsibility_ack=data.get("responsibility_ack", False),
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

    def post(self, request, pk):
        loan_request = get_object_or_404(visible_requests(request.user), pk=pk)
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            if self.action == "approve":
                loan_request = approve_request(loan_request, request.user, serializer.validated_data["notes"])
            else:
                loan_request = reject_request(loan_request, request.user, serializer.validated_data["notes"])
        except DjangoValidationError as exc:
            raise ValidationError(_drf_error(exc)) from None
        return Response(_request_data(loan_request, request.user))


class RequestApproveView(RequestDecisionView):
    action = "approve"


class RequestRejectView(RequestDecisionView):
    action = "reject"


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


class LoanListView(LoanAPIView):
    """List visible loans."""

    def get(self, request):
        queryset = visible_loans(request.user)
        status_filter = request.GET.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return Response({"results": [_loan_data(loan, request.user) for loan in queryset[:200]]})


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
            return_loan(loan, request.user, lines)
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
        staff = LoanStaff.objects.select_related("user", "created_by").all()
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
                for item in staff
            ]
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
        writer.writerow([
            "Reference", "Requester", "Status", "Purpose", "Pickup", "Return",
            "Items", "Created", "Decided by", "Decision notes",
        ])
        for item in visible_requests(request.user)[:5000]:
            writer.writerow([
                _csv_safe(item.reference),
                _csv_safe(item.requester),
                _csv_safe(item.get_status_display()),
                _csv_safe(item.purpose),
                _csv_safe(item.needed_by),
                _csv_safe(item.return_by),
                _csv_safe(item.item_count),
                _csv_safe(item.created.isoformat() if item.created else ""),
                _csv_safe(item.decided_by),
                _csv_safe(item.decision_notes),
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
        for loan in visible_loans(request.user)[:5000]:
            writer.writerow([
                _csv_safe(loan.reference),
                _csv_safe(loan.borrower),
                _csv_safe(loan.get_status_display()),
                _csv_safe(loan.issued_at.isoformat() if loan.issued_at else ""),
                _csv_safe(loan.due_at.isoformat() if loan.due_at else ""),
                _csv_safe(loan.returned_at.isoformat() if loan.returned_at else ""),
                _csv_safe(loan.item_count),
                _csv_safe(loan.renewals),
                _csv_safe(loan.notes),
            ])
        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="loans.csv"'
        return response
