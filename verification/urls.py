from django.urls import path

from . import views

urlpatterns = [
    path("verify/tax/", views.verify_tax_id, name="verify_tax"),
    path("verify/company/", views.verify_company_id, name="verify_company"),
    path("verify/ownership/", views.verify_ownership_view, name="verify_ownership"),
]
