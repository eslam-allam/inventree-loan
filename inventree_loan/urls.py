"""URL routes for the loan plugin."""

from django.urls import path

from . import views
from .api.views import (
    CatalogView,
    CheckoutView,
    ExportLoansView,
    ExportRequestsView,
    LoanDetailView,
    LoanItemLostView,
    LoanListView,
    LoanRenewView,
    LoanReturnView,
    QRCodeView,
    RequestApproveView,
    RequestCancelView,
    RequestDetailView,
    RequestListCreateView,
    RequestRejectView,
    ScanView,
    StaffDetailView,
    StaffListCreateView,
    StatsView,
    UserSearchView,
)

urlpatterns = [
    # Pages
    path("", views.dashboard, name="dashboard"),
    path("request/", views.request_new, name="request_new"),
    path("requests/", views.requests_view, name="requests"),
    path("requests/<int:pk>/", views.request_detail, name="request_detail"),
    path("loans/", views.loans_view, name="loans"),
    path("loans/<int:pk>/", views.loan_detail, name="loan_detail"),
    path("loans/<int:pk>/receipt/", views.receipt, name="receipt"),
    path("checkout/", views.checkout, name="checkout"),
    path("return/", views.return_page, name="return"),
    path("history/", views.history, name="history"),
    path("staff/", views.staff, name="staff"),
    path("setup/", views.setup, name="setup"),
    # JSON API
    path("api/catalog/", CatalogView.as_view(), name="api_catalog"),
    path("api/requests/", RequestListCreateView.as_view(), name="api_requests"),
    path(
        "api/requests/<int:pk>/",
        RequestDetailView.as_view(),
        name="api_request_detail",
    ),
    path(
        "api/requests/<int:pk>/approve/",
        RequestApproveView.as_view(),
        name="api_request_approve",
    ),
    path(
        "api/requests/<int:pk>/reject/",
        RequestRejectView.as_view(),
        name="api_request_reject",
    ),
    path(
        "api/requests/<int:pk>/cancel/",
        RequestCancelView.as_view(),
        name="api_request_cancel",
    ),
    path("api/loans/", LoanListView.as_view(), name="api_loans"),
    path("api/loans/<int:pk>/", LoanDetailView.as_view(), name="api_loan_detail"),
    path("api/checkout/", CheckoutView.as_view(), name="api_checkout"),
    path("api/loans/<int:pk>/return/", LoanReturnView.as_view(), name="api_loan_return"),
    path("api/loans/<int:pk>/renew/", LoanRenewView.as_view(), name="api_loan_renew"),
    path(
        "api/loans/<int:pk>/items/<int:item_pk>/lost/",
        LoanItemLostView.as_view(),
        name="api_loan_item_lost",
    ),
    path("api/scan/", ScanView.as_view(), name="api_scan"),
    path("api/stats/", StatsView.as_view(), name="api_stats"),
    path("api/user-search/", UserSearchView.as_view(), name="api_user_search"),
    path("api/staff/", StaffListCreateView.as_view(), name="api_staff"),
    path("api/staff/<int:pk>/", StaffDetailView.as_view(), name="api_staff_detail"),
    path("api/export/requests.csv", ExportRequestsView.as_view(), name="api_export_requests"),
    path("api/export/loans.csv", ExportLoansView.as_view(), name="api_export_loans"),
    path("qr/<int:pk>.svg", QRCodeView.as_view(), name="qr"),
]
