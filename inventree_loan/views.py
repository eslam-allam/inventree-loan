"""Server-rendered pages for the loan plugin."""

from __future__ import annotations

import mimetypes
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import http_date

from .config import get_native_management_url, get_setting
from .models import Loan, LoanRequest
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
from .services.requests import catalog_categories
from .services.setup import is_configured
from .utils import local_today


#: Directory containing the plugin's bundled static assets.
_ASSET_DIR = Path(__file__).resolve().parent / "static"


def _standard_admin_url() -> str:
    """Return the native InvenTree loan management page URL."""
    return get_native_management_url()


def asset(request, filename):
    """Serve a bundled plugin asset directly from the package.

    InvenTree normally serves plugin static files through ``collectplugins``.
    Serving them from the plugin's own URL avoids stale or missing collected
    copies (which previously caused the settings and management pages to load
    intermittently).  Only files directly inside the plugin ``static`` folder
    are allowed.
    """
    name = Path(filename).name
    if name != filename or name.startswith("."):
        raise Http404

    path = _ASSET_DIR / name
    if not path.is_file():
        raise Http404

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    stat = path.stat()
    response = FileResponse(path.open("rb"), content_type=content_type)
    # Plugin assets must not be served stale after an upgrade or an editable
    # install changes on disk.  Revalidate on every page load instead.
    response["Cache-Control"] = "private, no-cache, must-revalidate"
    response["Last-Modified"] = http_date(stat.st_mtime)
    return response


def _base_context(request, page: str, **extra) -> dict:
    role = get_user_role(request.user)
    authenticated = bool(request.user.is_authenticated)
    context = {
        "page": page,
        "loan_role": role,
        "is_authenticated": authenticated,
        "is_manager": can_view_all(request.user),
        "is_desk": can_handout(request.user),
        "is_admin": can_manage_staff(request.user),
        "can_request": can_request(request.user),
        "allow_anonymous_requests": bool(get_setting("ALLOW_ANONYMOUS_REQUESTS", True)),
        "setup_configured": is_configured(),
        "base_template": "inventree_loan/base_external.html",
        "loan_duration_days": int(get_setting("LOAN_DURATION_DAYS", 14) or 14),
        "due_soon_days": int(get_setting("DUE_SOON_DAYS", 2) or 2),
        "allow_direct_checkout": bool(get_setting("ALLOW_DIRECT_CHECKOUT", True)),
        "allow_renewal": bool(get_setting("ALLOW_RENEWAL", True)),
        "max_items": int(get_setting("MAX_ITEMS_PER_REQUEST", 25) or 25),
        "requester_name": (
            request.user.get_full_name() or request.user.username
            if authenticated
            else ""
        ),
        "requester_email": request.user.email if authenticated else "",
        "requester_phone": "",
    }
    context.update(extra)
    return context


@login_required
def dashboard(request):
    """Send admins to the native InvenTree console; requesters to the form."""
    if can_view_all(request.user):
        return redirect(_standard_admin_url())
    return redirect("plugin:loan:request_new")


def request_new(request):
    """Public requester form.

    The page intentionally does not require an InvenTree account.  Anonymous
    requesters provide their own name, email, phone and signature.
    """
    if not request.user.is_authenticated and not get_setting(
        "ALLOW_ANONYMOUS_REQUESTS", True
    ):
        raise PermissionDenied("Public loan requests are disabled")

    today = local_today()
    default_return = today + timedelta(
        days=int(get_setting("LOAN_DURATION_DAYS", 14) or 14)
    )
    context = _base_context(
        request,
        "request-new",
        today=today,
        default_return=default_return,
        public_mode=not request.user.is_authenticated,
        categories=catalog_categories(),
    )
    # The public form is available to everyone; the old group restriction only
    # applies to the authenticated account pages.
    context["can_request"] = True
    return render(request, "inventree_loan/request_form.html", context)


def public_request_detail(request, token):
    """Show request status and loan progress through a secret tracking token."""
    loan_request = get_object_or_404(
        LoanRequest.objects.select_related("requester").prefetch_related(
            "lines__part", "lines__stock_item"
        ),
        public_token=token,
    )
    return render(
        request,
        "inventree_loan/track_request.html",
        {
            "page": "track-request",
            "base_template": "inventree_loan/base_external.html",
            "request_obj": loan_request,
            "loan": Loan.objects.filter(request=loan_request).first(),
            "events": loan_request.events.all()[:100],
            "is_authenticated": bool(request.user.is_authenticated),
            "is_manager": can_view_all(request.user),
            "is_desk": can_handout(request.user),
            "is_admin": can_manage_staff(request.user),
            "can_request": True,
            "allow_anonymous_requests": bool(
                get_setting("ALLOW_ANONYMOUS_REQUESTS", True)
            ),
        },
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
