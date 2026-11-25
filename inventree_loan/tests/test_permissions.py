"""Permission and role tests for the loan plugin."""

from django.contrib.auth import get_user_model
from InvenTree.unit_test import InvenTreeTestCase

from inventree_loan.models import LoanStaff, LoanStaffRole
from inventree_loan.permissions import (
    can_approve,
    can_handout,
    can_manage_staff,
    can_request,
    get_user_role,
    is_manager,
)


class LoanPermissionTests(InvenTreeTestCase):
    """Check the plugin role hierarchy and requester defaults."""

    def setUp(self):
        super().setUp()
        self.other = get_user_model().objects.create_user(
            username="other", password="other-password"
        )

    def test_default_user_can_request_but_not_manage(self):
        self.assertTrue(can_request(self.user))
        self.assertFalse(is_manager(self.user))
        self.assertFalse(can_approve(self.user))
        self.assertFalse(can_handout(self.user))
        self.assertFalse(can_manage_staff(self.user))

    def test_role_hierarchy(self):
        LoanStaff.objects.create(user=self.user, role=LoanStaffRole.APPROVER)
        self.assertEqual(get_user_role(self.user), LoanStaffRole.APPROVER)
        self.assertTrue(can_approve(self.user))
        self.assertFalse(can_handout(self.user))

        staff = LoanStaff.objects.get(user=self.user)
        staff.role = LoanStaffRole.DESK
        staff.save()
        self.assertTrue(can_handout(self.user))
        self.assertFalse(can_manage_staff(self.user))

        staff.role = LoanStaffRole.ADMIN
        staff.save()
        self.assertTrue(can_manage_staff(self.user))

    def test_inactive_role_is_ignored(self):
        LoanStaff.objects.create(
            user=self.user, role=LoanStaffRole.DESK, active=False
        )
        self.assertFalse(is_manager(self.user))

    def test_superuser_is_admin(self):
        self.user.is_superuser = True
        self.user.save()
        self.assertEqual(get_user_role(self.user), LoanStaffRole.ADMIN)
        self.assertTrue(can_manage_staff(self.user))

    def test_other_user_does_not_inherit_role(self):
        LoanStaff.objects.create(user=self.user, role=LoanStaffRole.DESK)
        self.assertFalse(is_manager(self.other))
