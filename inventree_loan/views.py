"""Server-rendered pages for the loan plugin."""

from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .config import get_setting
from .models import LoanStaff, LoanStatus
from .permissions import (
    can_handout,
    can_manage_staff,
    can_request,
    can_view_all,
    get_user_role,
    is_manager,
)
from .selectors import (
    loan_with_items,
    request_with_lines,
    visible_events,
    visible_loans,
    visible_requests,
)
from .services.setup import ensure_setup, get_loan_location, get_on_loan_status, is_configured


def _base_context(request, page: str, **extra) -> dict:
    role = get_user_role(request.user)
    context = {
        "page": page,
        "loan_role": role,
        "is_manager": can_view_all(request.user),
        "is_desk": can_handout(request.user),
        "is_admin": can_manage_staff(request.user),
        "can_request": can_request(request.user),
        "setup_configured": is_configured(),
        "loan_duration_days": int(get_setting("LOAN_DURATION_DAYS", 14) or 14),
        "due_soon_days": int(get_setting("DUE_SOON_DAYS", 2) or 2),
        "allow_direct_checkout": bool(get_setting("ALLOW_DIRECT_CHECKOUT", True)),
        "allow_renewal": bool(get_setting("ALLOW_RENEWAL", True)),
        "max_items": int(get_setting("MAX_ITEMS_PER_REQUEST", 25) or 25),
    }
    context.update(extra)
    return context


@login_required
def dashboard(request):
    """Role-aware landing page."""
    now = timezone.now()
    due_cutoff = now + timedelta(days=int(get_setting("DUE_SOON_DAYS", 2) or 2))
    loans = visible_loans(request.user)
    requests = visible_requests(request.user)
    open_statuses = [LoanStatus.ACTIVE, LoanStatus.PARTIALLY_RETURNED, LoanStatus.OVERDUE]

    context = _base_context(
        request,
        "dashboard",
        stats={
            "pending": requests.filter(status="pending").count(),
            "approved": requests.filter(status="approved").count(),
            "active": loans.filter(status__in=open_statuses).count(),
            "due_soon": loans.filter(
                status__in=open_statuses, due_at__gte=now, due_at__lte=due_cutoff
            ).count(),
            "overdue": loans.filter(
                status__in=open_statuses,
                due_at__lt=now,
            ).count(),
        },
        pending_requests=(
            requests.filter(status="pending").select_related("requester")[:6]
            if can_view_all(request.user)
            else []
        ),
        due_loans=loans.filter(
            status__in=open_statuses, due_at__lte=due_cutoff
        ).select_related("borrower")[:6],
        active_loans=loans.filter(status__in=open_statuses).select_related("borrower")[:6],
        my_requests=requests.select_related("requester")[:6],
        recent_events=visible_events(request.user)[:8],
        setup_configured=is_configured(),
    )
    return render(request, "inventree_loan/dashboard.html", context)


@login_required
def request_new(request):
    """Requester-facing request wizard."""
    if not can_request(request.user):
        raise PermissionDenied("You do not have permission to request loans")

    today = timezone.localdate()
    default_return = today + timedelta(
        days=int(get_setting("LOAN_DURATION_DAYS", 14) or 14)
    )
    return render(
        request,
        "inventree_loan/request_form.html",
        _base_context(
            request,
            "request-new",
            today=today,
            default_return=default_return,
        ),
    )


@login_required
def requests_view(request):
    """My requests, or the approval queue for managers."""
    queryset = visible_requests(request.user)
    status_filter = request.GET.get("status", "").strip()
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    return render(
        request,
        "inventree_loan/requests.html",
        _base_context(
            request,
            "requests",
            requests=queryset[:200],
            status_filter=status_filter,
        ),
    )


@login_required
def request_detail(request, pk):
    """Request detail and decision actions."""
    loan_request = request_with_lines(request.user, pk)
    if loan_request is None:
        raise PermissionDenied("You cannot view this request")
    return render(
        request,
        "inventree_loan/request_detail.html",
        _base_context(
            request,
            "request-detail",
            request_obj=loan_request,
            events=loan_request.events.all()[:100],
        ),
    )


@login_required
def loans_view(request):
    """My loans, or all loans for managers."""
    queryset = visible_loans(request.user)
    status_filter = request.GET.get("status", "").strip()
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    return render(
        request,
        "inventree_loan/loans.html",
        _base_context(
            request,
            "loans",
            loans=queryset[:200],
            status_filter=status_filter,
        ),
    )


@login_required
def loan_detail(request, pk):
    """Loan detail and return/renew actions."""
    loan = loan_with_items(request.user, pk)
    if loan is None:
        raise PermissionDenied("You cannot view this loan")
    return render(
        request,
        "inventree_loan/loan_detail.html",
        _base_context(
            request,
            "loan-detail",
            loan=loan,
            events=loan.events.all()[:100],
        ),
    )


@login_required
def checkout(request):
    """Loan desk handout page."""
    if not can_handout(request.user):
        raise PermissionDenied("You need loan desk permission")

    selected_request = None
    request_id = request.GET.get("request_id")
    if request_id:
        selected_request = request_with_lines(request.user, request_id)
        if selected_request is None:
            raise PermissionDenied("You cannot view this request")

    return render(
        request,
        "inventree_loan/checkout.html",
        _base_context(
            request,
            "checkout",
            selected_request=selected_request,
            default_due=(
                selected_request.return_by
                if selected_request and selected_request.return_by
                else timezone.localdate()
                + timedelta(days=int(get_setting("LOAN_DURATION_DAYS", 14) or 14))
            ),
        ),
    )


@login_required
def return_page(request):
    """Loan desk return page."""
    if not can_handout(request.user):
        raise PermissionDenied("You need loan desk permission")

    loan = None
    loan_id = request.GET.get("loan_id")
    if loan_id:
        loan = loan_with_items(request.user, loan_id)
        if loan is None:
            raise PermissionDenied("You cannot view this loan")

    return render(
        request,
        "inventree_loan/return.html",
        _base_context(request, "return", selected_loan=loan),
    )


@login_required
def history(request):
    """Global audit history for managers."""
    if not is_manager(request.user):
        raise PermissionDenied("You need loan manager permission")

    events = visible_events(request.user)
    event_type = request.GET.get("event_type", "").strip()
    if event_type:
        events = events.filter(event_type=event_type)

    return render(
        request,
        "inventree_loan/history.html",
        _base_context(
            request,
            "history",
            events=events[:300],
            event_type=event_type,
        ),
    )


@login_required
def staff(request):
    """Manage plugin-level staff roles."""
    if not can_manage_staff(request.user):
        raise PermissionDenied("You need loan administrator permission")

    return render(
        request,
        "inventree_loan/staff.html",
        _base_context(
            request,
            "staff",
            staff=LoanStaff.objects.select_related("user", "created_by").all(),
        ),
    )


@login_required
def setup(request):
    """Setup wizard for the loan location and custom status."""
    if not can_manage_staff(request.user):
        raise PermissionDenied("You need loan administrator permission")

    if request.method == "POST":
        create_location = bool(request.POST.get("create_location"))
        location_name = (request.POST.get("location_name") or "On Loan").strip()
        try:
            result = ensure_setup(
                create_location=create_location,
                location_name=location_name or "On Loan",
            )
            if result.get("location") is None:
                messages.warning(
                    request,
                    "The custom status is ready, but no On Loan location is configured.",
                )
            else:
                messages.success(request, "Loan setup updated successfully.")
        except Exception as exc:  # pragma: no cover - shown to the administrator
            messages.error(request, f"Setup failed: {exc}")
        return redirect("plugin:loan:setup")

    return render(
        request,
        "inventree_loan/setup.html",
        _base_context(
            request,
            "setup",
            loan_location=get_loan_location(),
            on_loan_status=get_on_loan_status(),
            plugin_settings_url="/web/settings/admin/plugin/",
        ),
    )


@login_required
def receipt(request, pk):
    """Printable loan receipt with QR code."""
    loan = loan_with_items(request.user, pk)
    if loan is None:
        raise PermissionDenied("You cannot view this loan")
    return render(
        request,
        "inventree_loan/receipt.html",
        {
            "loan": loan,
            "qr_url": reverse("plugin:loan:qr", args=[loan.pk]),
        },
    )
