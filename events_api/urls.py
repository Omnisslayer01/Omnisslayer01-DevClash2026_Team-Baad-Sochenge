from django.urls import include, path
from rest_framework.routers import DefaultRouter

from events_api import views

router = DefaultRouter()
router.register(
    r"payment-accounts",
    views.OrganizerPaymentAccountViewSet,
    basename="payment-account",
)
router.register(r"events", views.EventViewSet, basename="event")
router.register(
    r"enrollments",
    views.EventEnrollmentViewSet,
    basename="enrollment",
)
router.register(r"wallet", views.PlatformWalletViewSet, basename="platform-wallet")
router.register(r"grievances", views.EventGrievanceViewSet, basename="event-grievance")
router.register(
    r"admin-wallet-payouts",
    views.AdminWalletPayoutViewSet,
    basename="admin-wallet-payout",
)

urlpatterns = [
    path("", include(router.urls)),
]
