"""Server-rendered pages for the loan plugin."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .config import get_admin_console_url, get_setting
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
    visible_loans,
    visible_requests,
)
from .services.setup import is_configured


def _standard_admin_url() -> str:
    """Return the native InvenTree plugin administration page URL."""
    return get_admin_console_url()


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
        "base_template": "inventree_loan/base_external.html",
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
    """Send admins to the native InvenTree console; requesters to the form."""
    if can_view_all(request.user):
        return redirect(_standard_admin_url())
    return redirect("plugin:loan:request_new")


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
    """Requesters see only their own requests; managers use the native console."""
    if can_view_all(request.user):
        return redirect(_standard_admin_url())
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
    """Request detail for the requester; managers use the native console."""
    if can_view_all(request.user):
        return redirect(_standard_admin_url())
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
    """Requesters see only their own loans; managers use the native console."""
    if can_view_all(request.user):
        return redirect(_standard_admin_url())
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
    """Loan detail for the borrower; managers use the native console."""
    if can_view_all(request.user):
        return redirect(_standard_admin_url())
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
    """Redirect legacy handout page to the native InvenTree console."""
    if not can_handout(request.user):
        raise PermissionDenied("You need loan desk permission")
    return redirect(_standard_admin_url())


@login_required
def return_page(request):
    """Redirect legacy return page to the native InvenTree console."""
    if not can_handout(request.user):
        raise PermissionDenied("You need loan desk permission")
    return redirect(_standard_admin_url())


@login_required
def history(request):
    """Redirect legacy history page to the native InvenTree console."""
    if not is_manager(request.user):
        raise PermissionDenied("You need loan manager permission")
    return redirect(_standard_admin_url())


@login_required
def staff(request):
    """Redirect legacy staff page to the native InvenTree console."""
    if not can_manage_staff(request.user):
        raise PermissionDenied("You need loan administrator permission")
    return redirect(_standard_admin_url())


@login_required
def setup(request):
    """Redirect legacy setup page to the native InvenTree console."""
    if not can_manage_staff(request.user):
        raise PermissionDenied("You need loan administrator permission")
    return redirect(_standard_admin_url())


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
