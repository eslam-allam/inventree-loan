"""Query helpers that keep user data scoped to the current user."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from .models import Loan, LoanEvent, LoanRequest
from .permissions import can_view_all


def visible_requests(user) -> QuerySet[LoanRequest]:
    """Return only requests the user is allowed to see.

    Keep this queryset light: list endpoints annotate the few aggregate fields
    they need, while detail views add the related rows explicitly.
    """
    queryset = LoanRequest.objects.select_related(
        "requester", "decided_by", "loan", "pickup"
    )
    if can_view_all(user):
        return queryset
    return queryset.filter(requester=user)


def visible_loans(user) -> QuerySet[Loan]:
    """Return only loans the user is allowed to see."""
    queryset = Loan.objects.select_related(
        "borrower", "issued_by", "request", "request__requester", "checkout_location"
    )
    if can_view_all(user):
        return queryset
    return queryset.filter(borrower=user)


def visible_events(user) -> QuerySet[LoanEvent]:
    """Return audit events for loans/requests the user may see."""
    queryset = LoanEvent.objects.select_related(
        "actor", "loan", "request", "loan__borrower", "request__requester"
    )
    if can_view_all(user):
        return queryset
    return queryset.filter(
        models_q_for_user(user)
    )


def models_q_for_user(user):
    """Build a Q object for events belonging to the user."""

    return Q(loan__borrower=user) | Q(request__requester=user)


def request_with_lines(user, pk: int) -> LoanRequest | None:
    """Return a visible request with its lines preloaded."""
    return (
        visible_requests(user)
        .prefetch_related(
            "lines__part",
            "lines__stock_item",
            "lines__allocations__stock_item__location",
            "events",
        )
        .filter(pk=pk)
        .first()
    )


def loan_with_items(user, pk: int) -> Loan | None:
    """Return a visible loan with its items preloaded."""
    return (
        visible_loans(user)
        .prefetch_related(
            "items__part",
            "items__stock_item",
            "items__original_location",
            "events",
        )
        .filter(pk=pk)
        .first()
    )


def pending_requests(user) -> QuerySet[LoanRequest]:
    """Pending requests visible to the user."""
    return visible_requests(user).filter(status="pending")


def active_loans(user) -> QuerySet[Loan]:
    """Open loans visible to the user."""
    return visible_loans(user).filter(status__in=["active", "partially_returned", "overdue"])
