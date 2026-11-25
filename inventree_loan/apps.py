"""Django application configuration for the loan plugin."""

from django.apps import AppConfig


class InvenTreeLoanConfig(AppConfig):
    """Configuration for the InvenTree Loan Manager app."""

    name = "inventree_loan"
    verbose_name = "InvenTree Loan Manager"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """Connect allocation guards after all models are loaded."""
        from .signals import connect_signals

        connect_signals()
