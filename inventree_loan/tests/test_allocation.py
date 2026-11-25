"""Allocation service and availability tests."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from InvenTree.unit_test import InvenTreeTestCase
from part.models import Part, PartCategory
from stock.models import StockItem, StockLocation
from stock.status_codes import StockStatus

from inventree_loan.models import (
    LoanRequest,
    LoanRequestAllocation,
    LoanRequestLine,
    LoanRequestStatus,
    LoanStaff,
    LoanStaffRole,
)
from inventree_loan.services.allocation import (
    add_allocation,
    auto_allocate_request,
    clear_allocations,
)
from inventree_loan.services.checkout import checkout_request
from inventree_loan.services.requests import (
    _validate_lines,
    part_availability,
)

TEST_SIGNATURE = "data:image/png;base64,AAAA"


class LoanAllocationTests(InvenTreeTestCase):
    """Allocation planning, availability and checkout integration."""

    def setUp(self):
        super().setUp()
        self.desk_user = get_user_model().objects.create_user(
            username="allocation-desk", password="desk-password"
        )
        LoanStaff.objects.create(user=self.desk_user, role=LoanStaffRole.DESK)

        self.category = PartCategory.objects.create(name="Allocation Category")
        self.part = Part.objects.create(
            name="Allocation Part", category=self.category, IPN="ALLOC-1"
        )
        self.location = StockLocation.objects.create(name="Allocation Shelf")
        self.loan_location = StockLocation.objects.create(name="Allocation Loan")
        self.stock_item = StockItem.objects.create(
            part=self.part,
            location=self.location,
            quantity=Decimal("5"),
            status=StockStatus.OK.value,
        )
        self.request = LoanRequest.objects.create(
            requester=self.user,
            status=LoanRequestStatus.APPROVED,
            purpose="Allocation testing",
            responsibility_ack=True,
        )
        self.line = LoanRequestLine.objects.create(
            request=self.request,
            part=self.part,
            quantity=Decimal("2"),
        )

    @patch("inventree_loan.services.checkout.get_loan_location")
    @patch("inventree_loan.services.checkout.get_on_loan_status_key")
    @patch("inventree_loan.services.requests._loan_location")
    def test_auto_allocate_does_not_move_stock(
        self, request_location, status_key, checkout_location
    ):
        request_location.return_value = self.loan_location
        status_key.return_value = StockStatus.QUARANTINED.value
        checkout_location.return_value = self.loan_location

        auto_allocate_request(self.request, self.desk_user)
        allocation = self.line.allocations.get()
        self.assertEqual(allocation.quantity, Decimal("2"))
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantity, Decimal("5"))
        self.assertEqual(self.stock_item.location_id, self.location.pk)
        self.assertEqual(part_availability(self.part)["available"], Decimal("3"))

    @patch("inventree_loan.services.checkout.get_loan_location")
    @patch("inventree_loan.services.checkout.get_on_loan_status_key")
    @patch("inventree_loan.services.requests._loan_location")
    def test_checkout_uses_allocations_and_releases_them(
        self, request_location, status_key, checkout_location
    ):
        request_location.return_value = self.loan_location
        status_key.return_value = StockStatus.QUARANTINED.value
        checkout_location.return_value = self.loan_location

        auto_allocate_request(self.request, self.desk_user)
        loan = checkout_request(
            self.request, self.desk_user, signature=TEST_SIGNATURE
        )
        self.assertEqual(loan.items.count(), 1)
        self.assertEqual(loan.items.get().quantity, Decimal("2"))
        self.assertFalse(
            LoanRequestAllocation.objects.filter(line__request=self.request).exists()
        )

    @patch("inventree_loan.services.requests._loan_location")
    def test_public_availability_blocks_over_requesting(self, request_location):
        request_location.return_value = self.loan_location
        with self.assertRaises(ValidationError):
            _validate_lines([{"part_id": self.part.pk, "quantity": 10}])

    @patch("inventree_loan.services.checkout.get_loan_location")
    @patch("inventree_loan.services.checkout.get_on_loan_status_key")
    @patch("inventree_loan.services.requests._loan_location")
    def test_serialized_item_allocation(
        self, request_location, status_key, checkout_location
    ):
        request_location.return_value = self.loan_location
        status_key.return_value = StockStatus.QUARANTINED.value
        checkout_location.return_value = self.loan_location

        serial_part = Part.objects.create(
            name="Serialized Allocation Part",
            category=self.category,
            trackable=True,
        )
        serial_item = StockItem.objects.create(
            part=serial_part,
            location=self.location,
            quantity=Decimal("1"),
            serial="ALLOC-SN-1",
            status=StockStatus.OK.value,
        )
        line = LoanRequestLine.objects.create(
            request=self.request, part=serial_part, quantity=Decimal("1")
        )
        auto_allocate_request(self.request, self.desk_user)
        allocation = line.allocations.get()
        self.assertEqual(allocation.stock_item_id, serial_item.pk)
        self.assertEqual(allocation.quantity, Decimal("1"))
        with self.assertRaises(ValidationError):
            add_allocation(
                self.request,
                self.desk_user,
                line_id=line.pk,
                stock_item_id=serial_item.pk,
                quantity=2,
            )

    @patch("inventree_loan.services.requests._loan_location")
    def test_clear_allocations_releases_stock(self, request_location):
        request_location.return_value = self.loan_location
        auto_allocate_request(self.request, self.desk_user)
        clear_allocations(self.request, self.desk_user)
        self.assertFalse(self.line.allocations.exists())
        self.assertEqual(part_availability(self.part)["available"], Decimal("5"))
