"""Authorization helpers for the loan plugin.

The plugin owns its staff roles because InvenTree 1.5.x does not expose
plugin-defined roles in the core group permission editor.  Every view and
service still performs object-level ownership checks.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

ROLE_APPROVER = "approver"
ROLE_DESK = "desk"
ROLE_ADMIN = "admin"

ROLE_LEVEL = {
    ROLE_APPROVER: 1,
    ROLE_DESK: 2,
    ROLE_ADMIN: 3,
}


def get_user_role(user) -> str | None:
    """Return the user's active loan role, or None."""
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return ROLE_ADMIN

    from .models import LoanStaff

    return (
        LoanStaff.objects.filter(user=user, active=True)
        .values_list("role", flat=True)
        .first()
    )


def role_level(user) -> int:
    """Return the numeric level of the user's loan role."""
    role = get_user_role(user)
    return ROLE_LEVEL.get(role, 0)


def is_manager(user, minimum: str = ROLE_APPROVER) -> bool:
    """Return True if the user has at least the requested loan role."""
    return role_level(user) >= ROLE_LEVEL.get(minimum, 1)


def is_loan_admin(user) -> bool:
    """Return True if the user can manage loan staff and settings."""
    return is_manager(user, ROLE_ADMIN)


def can_view_all(user) -> bool:
    """Return True if the user can view every request and loan."""
    return is_manager(user, ROLE_APPROVER)


def can_approve(user) -> bool:
    """Return True if the user can approve or reject requests."""
    return is_manager(user, ROLE_APPROVER)


def can_handout(user) -> bool:
    """Return True if the user can issue or receive items."""
    return is_manager(user, ROLE_DESK)


def can_manage_staff(user) -> bool:
    """Return True if the user can manage plugin staff roles."""
    return is_manager(user, ROLE_ADMIN)


def can_request(user) -> bool:
    """Return True if the user may submit loan requests."""
    if not user or not user.is_authenticated:
        return False

    from .config import get_request_group

    group = get_request_group()
    if not group:
        return True

    group_id = getattr(group, "pk", group)
    return user.groups.filter(pk=group_id).exists()


def can_view_request(user, request) -> bool:
    """Object-level request visibility."""
    if not user or not user.is_authenticated:
        return False
    return can_view_all(user) or request.requester_id == user.id


def can_edit_request(user, request) -> bool:
    """Only the requester can edit a pending request; managers may decide it."""
    if not user or not user.is_authenticated:
        return False
    from .models import LoanRequestStatus

    if can_view_all(user):
        return True
    return request.requester_id == user.id and request.status == LoanRequestStatus.PENDING


def can_cancel_request(user, request) -> bool:
    """The requester may cancel while open; managers may always cancel."""
    from .models import LoanRequestStatus

    if not user or not user.is_authenticated:
        return False
    if can_view_all(user):
        return request.status in {
            LoanRequestStatus.PENDING,
            LoanRequestStatus.APPROVED,
            LoanRequestStatus.PARTIALLY_APPROVED,
            LoanRequestStatus.READY_FOR_PICKUP,
            LoanRequestStatus.PARTIALLY_FULFILLED,
        }
    return request.requester_id == user.id and request.status in {
        LoanRequestStatus.PENDING,
        LoanRequestStatus.APPROVED,
        LoanRequestStatus.PARTIALLY_APPROVED,
        LoanRequestStatus.READY_FOR_PICKUP,
    }


def can_view_loan(user, loan) -> bool:
    """Object-level loan visibility."""
    if not user or not user.is_authenticated:
        return False
    return can_view_all(user) or loan.borrower_id == user.id


def raise_unless(condition: bool, message: str = "Permission denied"):
    """Raise a PermissionDenied when a condition is false."""
    if not condition:
        raise PermissionDenied(message)
