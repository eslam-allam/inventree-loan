"""Grant a plugin-level loan staff role from the command line."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from inventree_loan.models import LoanStaff, LoanStaffRole


class Command(BaseCommand):
    """Add or update a loan staff member."""

    help = "Grant a user an InvenTree Loan Manager role."

    def add_arguments(self, parser):
        parser.add_argument("username", help="InvenTree username")
        parser.add_argument(
            "--role",
            choices=[role.value for role in LoanStaffRole],
            default=LoanStaffRole.APPROVER.value,
        )
        parser.add_argument(
            "--inactive",
            action="store_true",
            help="Create/update the role as inactive.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError(f"User '{options['username']}' does not exist") from None

        staff, created = LoanStaff.objects.update_or_create(
            user=user,
            defaults={
                "role": options["role"],
                "active": not options["inactive"],
            },
        )
        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {staff.user} -> {staff.get_role_display()} "
                f"(active={staff.active})"
            )
        )
