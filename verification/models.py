"""
Simulated government-style records. Replace ORM access with HTTP clients later
without changing scoring or API contracts.
"""

from django.db import models


class Company(models.Model):
    """MCA-style company register entry."""

    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    cin = models.CharField(max_length=32, unique=True, db_index=True)
    legal_name = models.CharField(max_length=512)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, db_index=True)

    class Meta:
        ordering = ["cin"]
        verbose_name_plural = "companies"

    def __str__(self) -> str:
        return f"{self.cin} — {self.legal_name}"


class Director(models.Model):
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="directors"
    )
    full_name = models.CharField(max_length=256)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.full_name


class TaxRecord(models.Model):
    """GST register row linked to a company when known."""

    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_SUSPENDED = "suspended"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
        (STATUS_SUSPENDED, "Suspended"),
    ]

    gstin = models.CharField(max_length=15, unique=True, db_index=True)
    legal_name = models.CharField(max_length=512)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, db_index=True)
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tax_records",
    )

    class Meta:
        ordering = ["gstin"]

    def __str__(self) -> str:
        return f"{self.gstin} — {self.legal_name}"


class OwnershipClaim(models.Model):
    """Tracks who claimed which identifiers (fraud analytics)."""

    claimant_external_id = models.CharField(max_length=128, db_index=True)
    cin = models.CharField(max_length=32, db_index=True)
    gstin = models.CharField(max_length=15, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["cin", "claimant_external_id"]),
            models.Index(fields=["gstin"]),
        ]

    def __str__(self) -> str:
        return f"{self.claimant_external_id} @ {self.created_at:%Y-%m-%d}"


class FraudSignal(models.Model):
    """Structured fraud / inconsistency log (separate from application logs)."""

    SIGNAL_MULTI_CLAIM_CIN = "multi_claim_cin"
    SIGNAL_GSTIN_REUSE = "gstin_reuse"
    SIGNAL_NAME_MISMATCH = "name_mismatch"

    SIGNAL_CHOICES = [
        (SIGNAL_MULTI_CLAIM_CIN, "Multiple claimants for same CIN"),
        (SIGNAL_GSTIN_REUSE, "GSTIN claimed frequently"),
        (SIGNAL_NAME_MISMATCH, "Name mismatch across sources"),
    ]

    signal_type = models.CharField(max_length=64, choices=SIGNAL_CHOICES, db_index=True)
    severity = models.CharField(max_length=16, default="medium")
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.signal_type} ({self.severity})"
