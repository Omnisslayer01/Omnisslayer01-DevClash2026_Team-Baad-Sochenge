from django.contrib import admin

from . import models


@admin.register(models.Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("cin", "legal_name", "status")
    search_fields = ("cin", "legal_name")


@admin.register(models.Director)
class DirectorAdmin(admin.ModelAdmin):
    list_display = ("full_name", "company")
    search_fields = ("full_name",)


@admin.register(models.TaxRecord)
class TaxRecordAdmin(admin.ModelAdmin):
    list_display = ("gstin", "legal_name", "status", "company")
    search_fields = ("gstin", "legal_name")


@admin.register(models.OwnershipClaim)
class OwnershipClaimAdmin(admin.ModelAdmin):
    list_display = ("claimant_external_id", "cin", "gstin", "created_at")


@admin.register(models.FraudSignal)
class FraudSignalAdmin(admin.ModelAdmin):
    list_display = ("signal_type", "severity", "created_at")
    list_filter = ("signal_type", "severity")
