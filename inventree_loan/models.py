"""Database models for the InvenTree Loan Manager plugin."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class LoanRequestStatus(models.TextChoices):
    """Lifecycle states for a loan request."""

    PENDING = "pending", _("Pending approval")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    CANCELLED = "cancelled", _("Cancelled")
    FULFILLED = "fulfilled", _("Fulfilled")
    PARTIALLY_FULFILLED = "partially_fulfilled", _("Partially fulfilled")


class LoanStatus(models.TextChoices):
    """Lifecycle states for a loan."""

    ACTIVE = "active", _("On loan")
    PARTIALLY_RETURNED = "partially_returned", _("Partially returned")
    RETURNED = "returned", _("Returned")
    OVERDUE = "overdue", _("Overdue")
    CANCELLED = "cancelled", _("Cancelled")
    LOST = "lost", _("Lost")


class LoanStaffRole(models.TextChoices):
    """Plugin-level staff roles.

    InvenTree itself does not expose plugin-defined roles in its core group
    permission editor, so the plugin owns this small role table.
    """

    APPROVER = "approver", _("Approver")
    DESK = "desk", _("Loan desk")
    ADMIN = "admin", _("Loan administrator")


class LoanEventType(models.TextChoices):
    """Audit event types."""

    REQUESTED = "requested", _("Request submitted")
    APPROVED = "approved", _("Request approved")
    REJECTED = "rejected", _("Request rejected")
    CANCELLED = "cancelled", _("Request cancelled")
    ISSUED = "issued", _("Loan issued")
    PARTIALLY_RETURNED = "partially_returned", _("Items partially returned")
    RETURNED = "returned", _("Loan returned")
    RENEWED = "renewed", _("Loan renewed")
    DUE_SOON = "due_soon", _("Due soon reminder")
    OVERDUE = "overdue", _("Overdue reminder")
    LOST = "lost", _("Item marked lost")
    UPDATED = "updated", _("Record updated")
    STAFF_ADDED = "staff_added", _("Staff role granted")
    STAFF_REMOVED = "staff_removed", _("Staff role removed")
    SETUP = "setup", _("Plugin setup changed")


class ReturnCondition(models.TextChoices):
    """Condition choices recorded when an item is returned."""

    GOOD = "good", _("Good")
    DAMAGED = "damaged", _("Damaged")
    INCOMPLETE = "incomplete", _("Incomplete")
    OTHER = "other", _("Other")


class LoanBaseModel(models.Model):
    """Common timestamps for plugin records."""

    created = models.DateTimeField(auto_now_add=True, verbose_name=_("Created"))
    updated = models.DateTimeField(auto_now=True, verbose_name=_("Updated"))

    class Meta:
        abstract = True


class LoanRequest(LoanBaseModel):
    """A user's request to borrow one or more items."""

    REFERENCE_PREFIX = "REQ"

    reference = models.CharField(
        max_length=32,
        unique=True,
        blank=True,
        db_index=True,
        verbose_name=_("Reference"),
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loan_requests",
        verbose_name=_("Requester"),
    )
    status = models.CharField(
        max_length=24,
        choices=LoanRequestStatus.choices,
        default=LoanRequestStatus.PENDING,
        db_index=True,
        verbose_name=_("Status"),
    )
    purpose = models.TextField(blank=True, verbose_name=_("Purpose"))
    needed_by = models.DateField(
        null=True, blank=True, verbose_name=_("Pickup date")
    )
    return_by = models.DateField(
        null=True, blank=True, verbose_name=_("Requested return date")
    )
    notes = models.TextField(blank=True, verbose_name=_("Additional notes"))
    contact = models.CharField(
        max_length=255, blank=True, verbose_name=_("Contact details")
    )
    project = models.CharField(
        max_length=255, blank=True, verbose_name=_("Project / course / department")
    )
    responsibility_ack = models.BooleanField(
        default=False, verbose_name=_("Responsibility acknowledged")
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loan_requests_decided",
        verbose_name=_("Decided by"),
    )
    decided_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Decided at")
    )
    decision_notes = models.TextField(blank=True, verbose_name=_("Decision notes"))

    class Meta:
        ordering = ["-created"]
        verbose_name = _("Loan request")
        verbose_name_plural = _("Loan requests")
        indexes = [
            models.Index(fields=["status", "-created"]),
            models.Index(fields=["requester", "status"]),
        ]

    def __str__(self) -> str:
        return self.reference or f"Request #{self.pk}"

    def save(self, *args, **kwargs):
        """Assign a human-readable reference after the first save."""
        super().save(*args, **kwargs)
        if not self.reference:
            year = timezone.localdate().year
            self.reference = f"{self.REFERENCE_PREFIX}-{year}-{self.pk:04d}"
            type(self).objects.filter(pk=self.pk).update(reference=self.reference)

    @property
    def is_open(self) -> bool:
        """Return True if the request can still be acted on."""
        return self.status in {
            LoanRequestStatus.PENDING,
            LoanRequestStatus.APPROVED,
            LoanRequestStatus.PARTIALLY_FULFILLED,
        }

    @property
    def is_pending(self) -> bool:
        """Return True if approval is pending."""
        return self.status == LoanRequestStatus.PENDING

    @property
    def item_count(self) -> int:
        """Number of requested lines."""
        return self.lines.count()

    @property
    def total_quantity(self) -> Decimal:
        """Total requested quantity across all lines."""
        total = self.lines.aggregate(total=models.Sum("quantity"))["total"]
        return total or Decimal(0)

    @classmethod
    def check_user_permission(cls, user, permission: str) -> bool:
        """Class-level permission hook used by InvenTree's permission system.

        Object-level ownership is enforced by the plugin's views and selectors.
        """
        if not user or not user.is_authenticated:
            return False
        if permission == "add":
            return True
        from .permissions import is_manager

        return is_manager(user)


class LoanRequestLine(models.Model):
    """A single requested part or physical asset."""

    request = models.ForeignKey(
        LoanRequest,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("Request"),
    )
    part = models.ForeignKey(
        "part.Part",
        on_delete=models.PROTECT,
        related_name="loan_request_lines",
        verbose_name=_("Part"),
    )
    stock_item = models.ForeignKey(
        "stock.StockItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loan_request_lines",
        verbose_name=_("Specific stock item"),
    )
    quantity = models.DecimalField(
        max_digits=15,
        decimal_places=5,
        default=Decimal("1"),
        verbose_name=_("Quantity"),
    )
    notes = models.TextField(blank=True, verbose_name=_("Line notes"))

    class Meta:
        ordering = ["pk"]
        verbose_name = _("Loan request line")
        verbose_name_plural = _("Loan request lines")

    def __str__(self) -> str:
        return f"{self.part} x {self.quantity}"

    def clean(self):
        """Validate line data."""
        if self.quantity is None or self.quantity <= 0:
            raise ValidationError({"quantity": _("Quantity must be greater than zero")})
        if self.stock_item_id and self.part_id:
            if self.stock_item.part_id != self.part_id:
                raise ValidationError(
                    {"stock_item": _("The stock item does not belong to the selected part")}
                )
            if self.stock_item.serialized and self.quantity != 1:
                raise ValidationError(
                    {"quantity": _("A serialized stock item must have quantity 1")}
                )


class Loan(LoanBaseModel):
    """An issued loan, optionally linked to an approved request."""

    REFERENCE_PREFIX = "LOAN"

    reference = models.CharField(
        max_length=32,
        unique=True,
        blank=True,
        db_index=True,
        verbose_name=_("Reference"),
    )
    request = models.OneToOneField(
        LoanRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loan",
        verbose_name=_("Request"),
    )
    borrower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loans",
        verbose_name=_("Borrower"),
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loans_issued",
        verbose_name=_("Issued by"),
    )
    issued_at = models.DateTimeField(
        default=timezone.now, verbose_name=_("Issued at")
    )
    due_at = models.DateTimeField(db_index=True, verbose_name=_("Due at"))
    returned_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Returned at")
    )
    status = models.CharField(
        max_length=24,
        choices=LoanStatus.choices,
        default=LoanStatus.ACTIVE,
        db_index=True,
        verbose_name=_("Status"),
    )
    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name=_("QR token"),
    )
    notes = models.TextField(blank=True, verbose_name=_("Loan notes"))
    renewals = models.PositiveIntegerField(
        default=0, verbose_name=_("Renewal count")
    )
    checkout_location = models.ForeignKey(
        "stock.StockLocation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loans",
        verbose_name=_("Loan location"),
    )

    class Meta:
        ordering = ["-issued_at"]
        verbose_name = _("Loan")
        verbose_name_plural = _("Loans")
        indexes = [
            models.Index(fields=["status", "due_at"]),
            models.Index(fields=["borrower", "status"]),
            models.Index(fields=["-issued_at"]),
        ]

    def __str__(self) -> str:
        return self.reference or f"Loan #{self.pk}"

    def save(self, *args, **kwargs):
        """Assign a human-readable reference after the first save."""
        super().save(*args, **kwargs)
        if not self.reference:
            year = timezone.localdate().year
            self.reference = f"{self.REFERENCE_PREFIX}-{year}-{self.pk:05d}"
            type(self).objects.filter(pk=self.pk).update(reference=self.reference)

    @property
    def is_open(self) -> bool:
        """Return True while the loan still has items out."""
        return self.status in {
            LoanStatus.ACTIVE,
            LoanStatus.PARTIALLY_RETURNED,
            LoanStatus.OVERDUE,
        }

    @property
    def is_overdue(self) -> bool:
        """Return True if the loan is open and past its due date."""
        return self.is_open and self.due_at < timezone.now()

    @property
    def days_overdue(self) -> int:
        """Number of whole days overdue, or zero."""
        if not self.is_overdue:
            return 0
        delta = timezone.now() - self.due_at
        return max(delta.days + (1 if delta.seconds else 0), 1)

    @property
    def total_quantity(self) -> Decimal:
        """Total quantity issued on this loan."""
        total = self.items.aggregate(total=models.Sum("quantity"))["total"]
        return total or Decimal(0)

    @property
    def remaining_quantity(self) -> Decimal:
        """Total quantity still out on loan."""
        return sum((item.remaining_quantity for item in self.items.all()), Decimal(0))

    @property
    def item_count(self) -> int:
        """Number of lines on this loan."""
        return self.items.count()

    def refresh_status(self, save: bool = True) -> str:
        """Recalculate the loan status from its open items."""
        items = list(self.items.all())
        open_items = [item for item in items if item.is_open]
        any_returned = any(item.returned_quantity > 0 for item in items)
        all_lost = bool(items) and all(item.lost for item in items)

        if not open_items:
            if all_lost:
                status = LoanStatus.LOST
            else:
                status = LoanStatus.RETURNED
            self.returned_at = self.returned_at or timezone.now()
        elif self.due_at < timezone.now():
            status = LoanStatus.OVERDUE
            self.returned_at = None
        elif any_returned:
            status = LoanStatus.PARTIALLY_RETURNED
            self.returned_at = None
        else:
            status = LoanStatus.ACTIVE
            self.returned_at = None

        self.status = status
        if save:
            self.save(update_fields=["status", "returned_at", "updated"])
        return status

    @classmethod
    def check_user_permission(cls, user, permission: str) -> bool:
        """Class-level permission hook; object ownership is enforced in views."""
        if not user or not user.is_authenticated:
            return False
        from .permissions import is_manager

        if permission in {"add", "change", "delete"}:
            return is_manager(user)
        return is_manager(user)


class LoanItem(LoanBaseModel):
    """A physical stock item issued as part of a loan."""

    loan = models.ForeignKey(
        Loan,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("Loan"),
    )
    part = models.ForeignKey(
        "part.Part",
        on_delete=models.PROTECT,
        related_name="loan_items",
        verbose_name=_("Part"),
    )
    stock_item = models.ForeignKey(
        "stock.StockItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loan_items",
        verbose_name=_("Loaned stock item"),
    )
    stock_item_label = models.CharField(
        max_length=255, blank=True, verbose_name=_("Stock item label snapshot")
    )
    stock_item_serial = models.CharField(
        max_length=100, blank=True, verbose_name=_("Stock item serial snapshot")
    )
    original_stock_item = models.ForeignKey(
        "stock.StockItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loan_children",
        verbose_name=_("Original stock item"),
    )
    original_location = models.ForeignKey(
        "stock.StockLocation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loan_items_original",
        verbose_name=_("Original location"),
    )
    quantity = models.DecimalField(
        max_digits=15,
        decimal_places=5,
        default=Decimal("1"),
        verbose_name=_("Quantity"),
    )
    returned_quantity = models.DecimalField(
        max_digits=15,
        decimal_places=5,
        default=Decimal("0"),
        verbose_name=_("Returned quantity"),
    )
    status_on_issue = models.IntegerField(
        null=True, blank=True, verbose_name=_("Status on issue")
    )
    status_custom_key_on_issue = models.IntegerField(
        null=True, blank=True, verbose_name=_("Custom status on issue")
    )
    condition_on_issue = models.CharField(
        max_length=50, blank=True, verbose_name=_("Condition on issue")
    )
    condition_on_return = models.CharField(
        max_length=50,
        blank=True,
        choices=ReturnCondition.choices,
        verbose_name=_("Condition on return"),
    )
    returned_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Returned at")
    )
    return_notes = models.TextField(blank=True, verbose_name=_("Return notes"))
    lost = models.BooleanField(default=False, verbose_name=_("Lost"))
    lost_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Lost at"))

    class Meta:
        ordering = ["pk"]
        verbose_name = _("Loan item")
        verbose_name_plural = _("Loan items")
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "stock_item"], name="unique_loan_stock_item"
            )
        ]
        indexes = [
            models.Index(fields=["stock_item", "returned_at"]),
            models.Index(fields=["returned_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.part} x {self.quantity} ({self.loan})"

    @property
    def stock_item_display(self) -> str:
        """Human-readable stock item label, preserved after item deletion."""
        if self.stock_item_id:
            return str(self.stock_item)
        return self.stock_item_label or f"Stock item #{self.pk}"

    @property
    def remaining_quantity(self) -> Decimal:
        """Quantity still outstanding on this line."""
        return max(self.quantity - self.returned_quantity, Decimal(0))

    @property
    def is_open(self) -> bool:
        """Return True if this line still has items out."""
        return not self.lost and self.remaining_quantity > 0

    @property
    def is_returned(self) -> bool:
        """Return True if this line has been fully returned."""
        return self.remaining_quantity <= 0

    def clean(self):
        """Validate quantities."""
        if self.quantity is None or self.quantity <= 0:
            raise ValidationError({"quantity": _("Quantity must be greater than zero")})
        if self.returned_quantity < 0:
            raise ValidationError(
                {"returned_quantity": _("Returned quantity cannot be negative")}
            )
        if self.returned_quantity > self.quantity:
            raise ValidationError(
                {"returned_quantity": _("Returned quantity cannot exceed quantity")}
            )

    @classmethod
    def check_user_permission(cls, user, permission: str) -> bool:
        """Class-level permission hook; ownership is enforced by the loan."""
        if not user or not user.is_authenticated:
            return False
        from .permissions import is_manager

        return is_manager(user)


class LoanEvent(models.Model):
    """Append-only audit event for requests and loans."""

    request = models.ForeignKey(
        LoanRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
        verbose_name=_("Request"),
    )
    loan = models.ForeignKey(
        Loan,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
        verbose_name=_("Loan"),
    )
    event_type = models.CharField(
        max_length=32, choices=LoanEventType.choices, db_index=True, verbose_name=_("Event")
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loan_events",
        verbose_name=_("Actor"),
    )
    actor_name = models.CharField(
        max_length=150, blank=True, verbose_name=_("Actor name")
    )
    notes = models.TextField(blank=True, verbose_name=_("Notes"))
    metadata = models.JSONField(default=dict, blank=True, verbose_name=_("Metadata"))
    created = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Created"))

    class Meta:
        ordering = ["-created"]
        verbose_name = _("Loan event")
        verbose_name_plural = _("Loan events")

    def __str__(self) -> str:
        return f"{self.get_event_type_display()} @ {self.created:%Y-%m-%d %H:%M}"

    @classmethod
    def record(
        cls,
        *,
        event_type: str,
        request: LoanRequest | None = None,
        loan: Loan | None = None,
        actor=None,
        notes: str = "",
        **metadata,
    ) -> LoanEvent:
        """Create an audit event with a snapshot of the actor's name."""
        return cls.objects.create(
            request=request,
            loan=loan,
            event_type=event_type,
            actor=actor,
            actor_name=str(actor)[:150] if actor else "",
            notes=notes,
            metadata=metadata,
        )

    @classmethod
    def check_user_permission(cls, user, permission: str) -> bool:
        """Audit records are readable by owners/managers and never editable."""
        if not user or not user.is_authenticated:
            return False
        from .permissions import is_manager

        if permission == "view":
            return is_manager(user)
        return False


class LoanStaff(LoanBaseModel):
    """Plugin-managed staff role for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="loan_staff",
        verbose_name=_("User"),
    )
    role = models.CharField(
        max_length=20,
        choices=LoanStaffRole.choices,
        default=LoanStaffRole.APPROVER,
        verbose_name=_("Role"),
    )
    active = models.BooleanField(default=True, verbose_name=_("Active"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loan_staff_created",
        verbose_name=_("Created by"),
    )

    class Meta:
        ordering = ["role", "user__username"]
        verbose_name = _("Loan staff role")
        verbose_name_plural = _("Loan staff roles")

    def __str__(self) -> str:
        return f"{self.user} ({self.get_role_display()})"

    @classmethod
    def check_user_permission(cls, user, permission: str) -> bool:
        """Only loan administrators can manage staff roles."""
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return cls.objects.filter(
            user=user, active=True, role=LoanStaffRole.ADMIN
        ).exists()
