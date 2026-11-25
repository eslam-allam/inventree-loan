"""URL routes for the loan plugin.

Views are imported lazily so that the plugin can be initialised before the
Django app (and its models) has been added to ``INSTALLED_APPS`` by AppMixin.
"""

from importlib import import_module

from django.urls import path


def _function_view(module_name: str, attribute: str, *, auth_exempt: bool = False):
    """Return a lazy wrapper around a function-based view."""

    def view(request, *args, **kwargs):
        module = import_module(module_name)
        return getattr(module, attribute)(request, *args, **kwargs)

    view.__name__ = f"lazy_{attribute}"
    if auth_exempt:
        view.auth_exempt = True
    return view


def _class_view(module_name: str, attribute: str, *, auth_exempt: bool = False):
    """Return a lazy wrapper around a class-based view."""

    def view(request, *args, **kwargs):
        module = import_module(module_name)
        return getattr(module, attribute).as_view()(request, *args, **kwargs)

    view.__name__ = f"lazy_{attribute}"
    if auth_exempt:
        view.auth_exempt = True
    return view


urlpatterns = [
    # Bundled UI assets, served without requiring collectplugins
    path(
        "assets/<str:filename>",
        _function_view("inventree_loan.views", "asset", auth_exempt=True),
        name="asset",
    ),
    # Pages
    path("", _function_view("inventree_loan.views", "dashboard"), name="dashboard"),
    path("request/", _function_view("inventree_loan.views", "request_new", auth_exempt=True), name="request_new"),
    path(
        "track/",
        _function_view("inventree_loan.views", "public_track_lookup", auth_exempt=True),
        name="public_track_lookup",
    ),
    path(
        "track/<uuid:token>/",
        _function_view("inventree_loan.views", "public_request_detail", auth_exempt=True),
        name="public_request_detail",
    ),
    path(
        "track/<uuid:token>/receipt/",
        _function_view("inventree_loan.views", "public_request_receipt", auth_exempt=True),
        name="public_request_receipt",
    ),
    path(
        "track/<uuid:token>/qr.svg",
        _class_view("inventree_loan.api.views", "PublicRequestQRCodeView", auth_exempt=True),
        name="public_request_qr",
    ),
    path(
        "external/",
        _function_view("inventree_loan.views", "request_new", auth_exempt=True),
        name="external",
    ),
    path("requests/", _function_view("inventree_loan.views", "requests_view"), name="requests"),
    path(
        "requests/<int:pk>/",
        _function_view("inventree_loan.views", "request_detail"),
        name="request_detail",
    ),
    path("loans/", _function_view("inventree_loan.views", "loans_view"), name="loans"),
    path(
        "loans/<int:pk>/",
        _function_view("inventree_loan.views", "loan_detail"),
        name="loan_detail",
    ),
    path(
        "loans/<int:pk>/receipt/",
        _function_view("inventree_loan.views", "receipt"),
        name="receipt",
    ),
    path("checkout/", _function_view("inventree_loan.views", "checkout"), name="checkout"),
    path("return/", _function_view("inventree_loan.views", "return_page"), name="return"),
    path("history/", _function_view("inventree_loan.views", "history"), name="history"),
    path("staff/", _function_view("inventree_loan.views", "staff"), name="staff"),
    path("setup/", _function_view("inventree_loan.views", "setup"), name="setup"),
    # Public JSON API (anonymous requesters)
    path(
        "api/public/catalog/categories/",
        _class_view("inventree_loan.api.views", "PublicCatalogCategoriesView", auth_exempt=True),
        name="api_public_catalog_categories",
    ),
    path(
        "api/public/catalog/",
        _class_view("inventree_loan.api.views", "PublicCatalogView", auth_exempt=True),
        name="api_public_catalog",
    ),
    path(
        "api/public/catalog/<int:pk>/",
        _class_view("inventree_loan.api.views", "PublicPartDetailView", auth_exempt=True),
        name="api_public_part_detail",
    ),
    path(
        "api/public/part-image/<int:pk>/",
        _class_view("inventree_loan.api.views", "PublicPartImageView", auth_exempt=True),
        name="api_public_part_image",
    ),
    path(
        "api/public/scan/",
        _class_view("inventree_loan.api.views", "PublicScanView", auth_exempt=True),
        name="api_public_scan",
    ),
    path(
        "api/public/requests/",
        _class_view("inventree_loan.api.views", "PublicRequestCreateView", auth_exempt=True),
        name="api_public_requests",
    ),
    path(
        "api/public/requests/lookup/",
        _class_view("inventree_loan.api.views", "PublicRequestLookupView", auth_exempt=True),
        name="api_public_request_lookup",
    ),
    path(
        "api/public/requests/<uuid:token>/",
        _class_view("inventree_loan.api.views", "PublicRequestDetailView", auth_exempt=True),
        name="api_public_request_detail",
    ),
    # JSON API
    path(
        "api/catalog/",
        _class_view("inventree_loan.api.views", "CatalogView"),
        name="api_catalog",
    ),
    path(
        "api/requests/",
        _class_view("inventree_loan.api.views", "RequestListCreateView"),
        name="api_requests",
    ),
    path(
        "api/requests/<int:pk>/",
        _class_view("inventree_loan.api.views", "RequestDetailView"),
        name="api_request_detail",
    ),
    path(
        "api/requests/<int:pk>/approve/",
        _class_view("inventree_loan.api.views", "RequestApproveView"),
        name="api_request_approve",
    ),
    path(
        "api/requests/<int:pk>/reject/",
        _class_view("inventree_loan.api.views", "RequestRejectView"),
        name="api_request_reject",
    ),
    path(
        "api/requests/<int:pk>/cancel/",
        _class_view("inventree_loan.api.views", "RequestCancelView"),
        name="api_request_cancel",
    ),
    path(
        "api/requests/<int:pk>/allocate/",
        _class_view("inventree_loan.api.views", "RequestAllocateView"),
        name="api_request_allocate",
    ),
    path(
        "api/requests/<int:pk>/allocations/candidates/",
        _class_view("inventree_loan.api.views", "RequestAllocationCandidatesView"),
        name="api_request_allocation_candidates",
    ),
    path(
        "api/requests/<int:pk>/allocations/<int:allocation_pk>/",
        _class_view("inventree_loan.api.views", "RequestAllocationDeleteView"),
        name="api_request_allocation_delete",
    ),
    path(
        "api/loans/",
        _class_view("inventree_loan.api.views", "LoanListView"),
        name="api_loans",
    ),
    path(
        "api/loans/<int:pk>/",
        _class_view("inventree_loan.api.views", "LoanDetailView"),
        name="api_loan_detail",
    ),
    path(
        "api/checkout/",
        _class_view("inventree_loan.api.views", "CheckoutView"),
        name="api_checkout",
    ),
    path(
        "api/loans/<int:pk>/return/",
        _class_view("inventree_loan.api.views", "LoanReturnView"),
        name="api_loan_return",
    ),
    path(
        "api/loans/<int:pk>/renew/",
        _class_view("inventree_loan.api.views", "LoanRenewView"),
        name="api_loan_renew",
    ),
    path(
        "api/loans/<int:pk>/items/<int:item_pk>/lost/",
        _class_view("inventree_loan.api.views", "LoanItemLostView"),
        name="api_loan_item_lost",
    ),
    path("api/scan/", _class_view("inventree_loan.api.views", "ScanView"), name="api_scan"),
    path("api/stats/", _class_view("inventree_loan.api.views", "StatsView"), name="api_stats"),
    path("api/setup/", _class_view("inventree_loan.api.views", "SetupView"), name="api_setup"),
    path(
        "api/events/",
        _class_view("inventree_loan.api.views", "EventListView"),
        name="api_events",
    ),
    path(
        "api/user-search/",
        _class_view("inventree_loan.api.views", "UserSearchView"),
        name="api_user_search",
    ),
    path(
        "api/staff/",
        _class_view("inventree_loan.api.views", "StaffListCreateView"),
        name="api_staff",
    ),
    path(
        "api/staff/<int:pk>/",
        _class_view("inventree_loan.api.views", "StaffDetailView"),
        name="api_staff_detail",
    ),
    path(
        "api/export/requests.csv",
        _class_view("inventree_loan.api.views", "ExportRequestsView"),
        name="api_export_requests",
    ),
    path(
        "api/export/loans.csv",
        _class_view("inventree_loan.api.views", "ExportLoansView"),
        name="api_export_loans",
    ),
    path("qr/<int:pk>.svg", _class_view("inventree_loan.api.views", "QRCodeView"), name="qr"),
]
