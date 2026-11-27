"""Pickup box/bag preparation for loan requests."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..models import (
    LoanEvent,
    LoanEventType,
    LoanPickup,
    LoanPickupStatus,
    LoanRequest,
    LoanRequestStatus,
)
from ..permissions import can_approve
from .notifications import notify_request_ready


def ensure_pickup(request: LoanRequest, actor=None) -> LoanPickup:
    """Return the pickup box for a request, creating it if necessary."""
    pickup, _created = LoanPickup.objects.get_or_create(
        request=request,
        defaults={"created_by": actor},
    )
    return pickup


@transaction.atomic
def mark_ready_for_pickup(
    request: LoanRequest,
    actor,
    *,
    name: str = "",
    notes: str = "",
) -> LoanPickup:
    """Pack a request and move it to the ready-for-pickup phase."""
    if not can_approve(actor):
        raise PermissionDenied("You do not have permission to prepare pickups")

    request = (
        LoanRequest.objects.select_for_update()
        .prefetch_related("lines__allocations")
        .get(pk=request.pk)
    )
    if request.status not in {
        LoanRequestStatus.APPROVED,
        LoanRequestStatus.PARTIALLY_APPROVED,
        LoanRequestStatus.READY_FOR_PICKUP,
    }:
        raise ValidationError(
            _("Only approved or partially approved requests can be marked ready")
        )
    if not request.lines.exists():
        raise ValidationError(_("This request has no items"))
    if not request.is_fully_allocated:
        raise ValidationError(
            _(
                "All approved items must be allocated before the request can be ready for pickup"
            )
        )

    pickup = ensure_pickup(request, actor)
    clean_name = (name or "").strip()
    if clean_name:
        pickup.name = clean_name
    if notes is not None:
        pickup.notes = (notes or "").strip()
    pickup.status = LoanPickupStatus.READY
    pickup.ready_at = pickup.ready_at or timezone.now()
    pickup.created_by = pickup.created_by or actor
    pickup.save(
        update_fields=[
            "name",
            "notes",
            "status",
            "ready_at",
            "created_by",
            "updated",
        ]
    )

    request.status = LoanRequestStatus.READY_FOR_PICKUP
    request.save(update_fields=["status", "updated"])

    LoanEvent.record(
        request=request,
        event_type=LoanEventType.READY_FOR_PICKUP,
        actor=actor,
        notes=(notes or "").strip()
        or f"Pickup box {pickup.reference} is ready",
    )
    notify_request_ready(request, pickup)
    return pickup


def collect_pickup(request: LoanRequest, actor=None) -> LoanPickup | None:
    """Mark a pickup box as collected when its request is handed out."""
    pickup = LoanPickup.objects.filter(request=request).first()
    if pickup is None:
        return None
    pickup.status = LoanPickupStatus.COLLECTED
    pickup.collected_at = timezone.now()
    pickup.save(update_fields=["status", "collected_at", "updated"])
    LoanEvent.record(
        request=request,
        event_type=LoanEventType.PICKUP_COLLECTED,
        actor=actor,
        notes=f"Pickup box {pickup.reference} collected",
    )
    return pickup


def cancel_pickup(request: LoanRequest, actor=None) -> None:
    """Cancel the pickup box when a request is cancelled or rejected."""
    pickup = LoanPickup.objects.filter(request=request).first()
    if pickup is None:
        return
    pickup.status = LoanPickupStatus.CANCELLED
    pickup.save(update_fields=["status", "updated"])
    LoanEvent.record(
        request=request,
        event_type=LoanEventType.UPDATED,
        actor=actor,
        notes=f"Pickup box {pickup.reference} cancelled",
    )
