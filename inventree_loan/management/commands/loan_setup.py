"""Create or repair the loan plugin's stock configuration."""

from django.core.management.base import BaseCommand

from inventree_loan.services.setup import ensure_setup


class Command(BaseCommand):
    """Create the On Loan status and optionally the On Loan location."""

    help = "Configure the InvenTree Loan Manager status and stock location."

    def add_arguments(self, parser):
        parser.add_argument(
            "--create-location",
            action="store_true",
            help="Create the On Loan stock location if it does not exist.",
        )
        parser.add_argument(
            "--location-name",
            default="On Loan",
            help="Name to use when creating the stock location.",
        )
        parser.add_argument(
            "--parent",
            type=int,
            default=None,
            help="Optional parent StockLocation primary key.",
        )

    def handle(self, *args, **options):
        parent = None
        if options.get("parent"):
            from stock.models import StockLocation

            parent = StockLocation.objects.get(pk=options["parent"])

        result = ensure_setup(
            create_location=options["create_location"],
            location_name=options["location_name"],
            parent=parent,
        )
        status = result.get("status")
        location = result.get("location")
        if status:
            self.stdout.write(
                self.style.SUCCESS(
                    f"On Loan status ready: {status.label} (key {status.key})."
                )
            )
        if location:
            self.stdout.write(
                self.style.SUCCESS(f"On Loan location ready: {location.pathstring}.")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "No On Loan location configured. Re-run with --create-location "
                    "or select one in the plugin settings."
                )
            )
