"""Notification helpers for in-app messages and optional email."""

from __future__ import annotations

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.mail import send_mail
from django.urls import reverse

from ..config import get_setting


def _truncate(value: str, length: int = 250) -> str:
    return (value or "")[:length]


def notify_user(user, name: str, message: str, target=None, link: str = ""):
    """Create an in-app notification for a single user."""
    if user is None or target is None:
        return
    from common.models import NotificationMessage

    try:
        NotificationMessage.objects.create(
            target_content_type=ContentType.objects.get_for_model(target),
            target_object_id=str(target.pk),
            user=user,
            category="loan",
            name=_truncate(name),
            message=_truncate(message),
            link=link or None,
        )
    except Exception:  # pragma: no cover - notifications must never break a loan action
        pass


def notify_users(users, name: str, message: str, target=None, link: str = ""):
    """Create in-app notifications for a collection of users."""
    seen = set()
    for user in users:
        if user is None or user.pk in seen:
            continue
        seen.add(user.pk)
        notify_user(user, name, message, target=target, link=link)


def manager_users():
    """Return active loan staff, with superusers as a fallback.

    Query ``LoanStaff`` directly instead of relying on the reverse accessor on
    the user model: InvenTree reloads plugin apps at runtime, which can drop
    reverse relations from the already-loaded User model.
    """
    from ..models import LoanStaff

    users = [
        staff.user
        for staff in LoanStaff.objects.filter(
            active=True, user__is_active=True
        ).select_related("user")
    ]
    if users:
        return users

    User = get_user_model()
    return list(User.objects.filter(is_superuser=True, is_active=True))


def send_email_address(email: str, subject: str, message: str):
    """Send email to an address, even when there is no user account."""
    email = (email or "").strip()
    if not email or not get_setting("ENABLE_EMAIL", False):
        return
    from_email = get_setting("EMAIL_FROM", "") or django_settings.DEFAULT_FROM_EMAIL
    try:
        send_mail(subject, message, from_email, [email], fail_silently=True)
    except Exception:  # pragma: no cover
        pass


def send_email(user, subject: str, message: str):
    """Send an email if the plugin and Django are configured for it."""
    if not user:
        return
    send_email_address(user.email, subject, message)


def request_link(request) -> str:
    """Absolute-ish URL for a request detail page."""
    if request.requester_id is None:
        try:
            return reverse(
                "plugin:loan:public_request_detail", args=[request.public_token]
            )
        except Exception:  # pragma: no cover
            return ""
    try:
        return reverse("plugin:loan:request_detail", args=[request.pk])
    except Exception:  # pragma: no cover
        return ""


def loan_link(loan) -> str:
    """Absolute-ish URL for a loan detail page."""
    if loan.borrower_id is None and loan.request_id:
        try:
            return reverse(
                "plugin:loan:public_request_detail",
                args=[loan.request.public_token],
            )
        except Exception:  # pragma: no cover
            return ""
    try:
        return reverse("plugin:loan:loan_detail", args=[loan.pk])
    except Exception:  # pragma: no cover
        return ""


def notify_request_submitted(request):
    """Notify approvers that a new request needs attention."""
    name = f"New loan request {request.reference}"
    message = f"{request.requester_display} requested {request.item_count} item(s)."
    link = request_link(request)
    managers = manager_users()
    notify_users(managers, name, message, target=request, link=link)
    for user in managers:
        send_email(user, name, f"{message}\n\n{link}")


def notify_request_decided(request):
    """Notify the requester about an approval, partial approval or rejection."""
    from ..models import LoanRequestStatus

    name = f"Loan request {request.reference} {request.get_status_display().lower()}"
    parts = [
        request.decision_notes
        or f"Your request is now {request.get_status_display()}."
    ]
    if request.status in {
        LoanRequestStatus.APPROVED,
        LoanRequestStatus.PARTIALLY_APPROVED,
    }:
        lines = list(request.lines.select_related("part"))
        approved = [
            f"{line.part.name} x {line.approved_quantity}"
            for line in lines
            if line.approved_quantity > 0
        ]
        remaining = [
            f"{line.part.name} x {line.quantity - line.approved_quantity}"
            for line in lines
            if line.approved_quantity < line.quantity
        ]
        if approved:
            parts.append("Approved: " + ", ".join(approved) + ".")
        if remaining:
            parts.append("Still awaiting approval: " + ", ".join(remaining) + ".")
    message = " ".join(parts)
    link = request_link(request)
    notify_user(request.requester, name, message, target=request, link=link)
    send_email_address(
        request.requester_email_display, name, f"{message}\n\n{link}"
    )


def notify_request_cancelled(request):
    """Notify the requester that a request was cancelled."""
    name = f"Loan request {request.reference} cancelled"
    message = request.decision_notes or "Your loan request was cancelled."
    link = request_link(request)
    notify_user(request.requester, name, message, target=request, link=link)
    send_email_address(
        request.requester_email_display, name, f"{message}\n\n{link}"
    )


def notify_request_ready(request, pickup=None):
    """Notify the requester that the packed items are ready to collect."""
    name = f"Loan request {request.reference} is ready for pickup"
    parts = ["Your items are packed and ready to collect."]
    if pickup is not None:
        parts.append(
            f"Pickup box: {pickup.display_name} ({pickup.reference})."
        )
    if request.needed_by:
        parts.append(f"Pickup date: {request.needed_by:%Y-%m-%d}.")
    message = " ".join(parts)
    link = request_link(request)
    notify_user(request.requester, name, message, target=request, link=link)
    send_email_address(
        request.requester_email_display, name, f"{message}\n\n{link}"
    )


def notify_loan_issued(loan):
    """Notify the borrower that items have been handed out."""
    from ..models import LoanRequestStatus

    name = f"Loan {loan.reference} issued"
    message = f"{loan.item_count} item(s) due {loan.due_at:%Y-%m-%d}."
    if loan.request_id and loan.request.status == LoanRequestStatus.PARTIALLY_FULFILLED:
        message += " Some requested items were not approved or issued."
    link = loan_link(loan)
    notify_user(loan.borrower, name, message, target=loan, link=link)
    send_email_address(loan.borrower_email_display, name, f"{message}\n\n{link}")


def notify_loan_returned(loan):
    """Notify the borrower that the loan is closed."""
    name = f"Loan {loan.reference} returned"
    message = "All items have been returned. Thank you."
    link = loan_link(loan)
    notify_user(loan.borrower, name, message, target=loan, link=link)
    send_email_address(loan.borrower_email_display, name, f"{message}\n\n{link}")


def notify_loan_partially_returned(loan):
    """Notify the borrower that part of a loan has been returned."""
    name = f"Loan {loan.reference} partially returned"
    message = (
        f"Your return was recorded. {loan.remaining_quantity} unit(s) remain "
        f"on loan until {loan.due_at:%Y-%m-%d}."
    )
    link = loan_link(loan)
    notify_user(loan.borrower, name, message, target=loan, link=link)
    send_email_address(loan.borrower_email_display, name, f"{message}\n\n{link}")


def notify_loan_renewed(loan):
    """Notify the borrower about a new due date."""
    name = f"Loan {loan.reference} renewed"
    message = f"The due date is now {loan.due_at:%Y-%m-%d}."
    link = loan_link(loan)
    notify_user(loan.borrower, name, message, target=loan, link=link)
    send_email_address(loan.borrower_email_display, name, f"{message}\n\n{link}")


def notify_loan_reminder(loan, overdue: bool = False):
    """Notify the borrower about an upcoming or missed due date."""
    if overdue:
        name = f"Loan {loan.reference} is overdue"
        message = f"Please return the items as soon as possible. Due {loan.due_at:%Y-%m-%d}."
    else:
        name = f"Loan {loan.reference} is due soon"
        message = f"Please return the items by {loan.due_at:%Y-%m-%d}."
    link = loan_link(loan)
    notify_user(loan.borrower, name, message, target=loan, link=link)
    send_email_address(loan.borrower_email_display, name, f"{message}\n\n{link}")


def notify_item_lost(loan_item):
    """Notify managers and the borrower when an item is marked lost."""
    loan = loan_item.loan
    name = f"Item marked lost on {loan.reference}"
    message = f"{loan_item.part} was marked lost."
    link = loan_link(loan)
    notify_user(loan.borrower, name, message, target=loan, link=link)
    notify_users(manager_users(), name, message, target=loan, link=link)
