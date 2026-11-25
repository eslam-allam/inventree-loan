"""Scheduled tasks for the loan plugin."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .config import get_setting
from .models import Loan, LoanEvent, LoanEventType, LoanStatus
from .services.notifications import notify_loan_reminder


def refresh_overdue_statuses() -> int:
    """Update open loans whose due date has passed."""
    changed = 0
    for loan in Loan.objects.filter(
        status__in=[LoanStatus.ACTIVE, LoanStatus.PARTIALLY_RETURNED, LoanStatus.OVERDUE]
    ).prefetch_related("items"):
        status = loan.refresh_status()
        if status == LoanStatus.OVERDUE:
            changed += 1
    return changed


def send_due_reminders() -> None:
    """Send due-soon and overdue reminders once per day per loan."""
    from common.models import NotificationEntry

    if not get_setting("SEND_DUE_REMINDERS", True):
        return

    now = timezone.now()
    due_soon_days = max(int(get_setting("DUE_SOON_DAYS", 2) or 2), 0)
    overdue_days = max(int(get_setting("OVERDUE_REMINDER_DAYS", 1) or 1), 1)

    refresh_overdue_statuses()

    for loan in Loan.objects.filter(
        status__in=[LoanStatus.ACTIVE, LoanStatus.PARTIALLY_RETURNED, LoanStatus.OVERDUE]
    ).select_related("borrower"):
        if loan.due_at < now:
            key = "loan_overdue"
            if NotificationEntry.check_recent(key, loan.pk, timedelta(days=overdue_days)):
                continue
            notify_loan_reminder(loan, overdue=True)
            LoanEvent.record(
                loan=loan,
                event_type=LoanEventType.OVERDUE,
                notes="Overdue reminder sent",
            )
            NotificationEntry.notify(key, loan.pk)
        elif loan.due_at <= now + timedelta(days=due_soon_days):
            key = "loan_due_soon"
            if NotificationEntry.check_recent(key, loan.pk, timedelta(days=1)):
                continue
            notify_loan_reminder(loan, overdue=False)
            LoanEvent.record(
                loan=loan,
                event_type=LoanEventType.DUE_SOON,
                notes="Due-soon reminder sent",
            )
            NotificationEntry.notify(key, loan.pk)
