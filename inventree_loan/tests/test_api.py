"""API visibility and permission tests."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from InvenTree.unit_test import InvenTreeAPITestCase
from part.models import Part, PartCategory
from stock.models import StockItem, StockLocation
from stock.status_codes import StockStatus

TEST_SIGNATURE = "data:image/png;base64,AAAA"

from inventree_loan.services.requests import create_request

from inventree_loan.models import (
    LoanRequest,
    LoanRequestLine,
    LoanRequestStatus,
    LoanStaff,
    LoanStaffRole,
)


class LoanAPIPermissionTests(InvenTreeAPITestCase):
    """Check object-level visibility and approval permissions."""

    def setUp(self):
        super().setUp()
        self.other = get_user_model().objects.create_user(
            username="other-user", password="other-password"
        )
        self.approver = get_user_model().objects.create_user(
            username="approver-user", password="approver-password"
        )
        LoanStaff.objects.create(user=self.approver, role=LoanStaffRole.APPROVER)

        self.category = PartCategory.objects.create(name="API Loan Category")
        self.part = Part.objects.create(
            name="API Loan Part", category=self.category, IPN="API-LOAN"
        )
        self.location = StockLocation.objects.create(name="API Loan Shelf")
        StockItem.objects.create(
            part=self.part,
            location=self.location,
            quantity=Decimal("10"),
            status=StockStatus.OK.value,
        )
        self.request = LoanRequest.objects.create(
            requester=self.user,
            status=LoanRequestStatus.PENDING,
            purpose="API testing",
            responsibility_ack=True,
        )
        LoanRequestLine.objects.create(
            request=self.request,
            part=self.part,
            quantity=Decimal("1"),
        )

    def test_requester_can_create_request(self):
        response = self.client.post(
            "/plugin/loan/api/requests/",
            {
                "lines": [{"part_id": self.part.pk, "quantity": 2}],
                "purpose": "Need it for a demo",
                "needed_by": "2030-01-01",
                "return_by": "2030-01-08",
                "responsibility_ack": True,
                "signature": TEST_SIGNATURE,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["reference"].startswith("REQ-"))
        self.assertEqual(response.data["status"], LoanRequestStatus.PENDING)

    def test_requester_cannot_view_another_users_request(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.get(f"/plugin/loan/api/requests/{self.request.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_requester_cannot_approve(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.post(
            f"/plugin/loan/api/requests/{self.request.pk}/approve/",
            {"notes": "should fail"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, LoanRequestStatus.PENDING)

    def test_approver_can_approve(self):
        self.client.force_authenticate(user=self.approver)
        response = self.client.post(
            f"/plugin/loan/api/requests/{self.request.pk}/approve/",
            {"notes": "Approved for demo"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, LoanRequestStatus.APPROVED)
        self.assertEqual(self.request.decision_notes, "Approved for demo")
        self.assertEqual(self.request.decided_by, self.approver)

    def test_anonymous_request_tracking_and_receipt(self):
        created = create_request(
            None,
            [{"part_id": self.part.pk, "quantity": 1}],
            requester_name="Anonymous Requester",
            requester_email="anon@example.com",
            purpose="Tracking test",
            responsibility_ack=True,
            signature=TEST_SIGNATURE,
            allow_anonymous=True,
        )
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/plugin/loan/request/").status_code, 200)
        self.assertEqual(
            self.client.get(f"/plugin/loan/track/{created.public_token}/").status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/plugin/loan/track/{created.public_token}/receipt/"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/plugin/loan/track/{created.public_token}/qr.svg"
            ).status_code,
            200,
        )
        lookup = self.client.post(
            "/plugin/loan/api/public/requests/lookup/",
            {"reference": created.reference, "email": "anon@example.com"},
            format="json",
        )
        self.assertEqual(lookup.status_code, 200)
        wrong = self.client.post(
            "/plugin/loan/api/public/requests/lookup/",
            {"reference": created.reference, "email": "wrong@example.com"},
            format="json",
        )
        self.assertEqual(wrong.status_code, 404)

    def test_public_request_rejects_fractional_quantity(self):
        from inventree_loan.api.serializers import PublicRequestCreateSerializer

        serializer = PublicRequestCreateSerializer(
            data={
                "requester_name": "Anon",
                "requester_email": "anon@example.com",
                "signature": TEST_SIGNATURE,
                "purpose": "Fraction test",
                "responsibility_ack": True,
                "lines": [{"part_id": self.part.pk, "quantity": 1.5}],
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("lines", serializer.errors)

    def test_catalog_is_requester_safe(self):
        response = self.client.get("/plugin/loan/api/catalog/?search=API")
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertTrue(results)
        self.assertEqual(results[0]["pk"], self.part.pk)
        self.assertNotIn("purchase_price", results[0])

    def test_scan_unknown_barcode_returns_error_payload(self):
        response = self.client.post(
            "/plugin/loan/api/scan/",
            {"barcode": "definitely-not-a-known-barcode"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["success"])
