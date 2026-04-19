import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    full_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(
        max_length=20,
        choices=[("professional", "Professional"), ("company", "Company")],
        default="professional",
    )
    is_verified = models.BooleanField(default=False)
    is_verified_human = models.BooleanField(default=False)
    trust_score = models.IntegerField(default=20)
    is_reported = models.BooleanField(default=False)

    def __str__(self):
        return self.username

CLAIM_NONE = ""
CLAIM_EMPLOYEE = "employee"
CLAIM_OWNER = "owner"
CLAIM_ORGANISER = "organiser"

CLAIM_TYPE_CHOICES = [
    (CLAIM_NONE, "Not upgrading"),
    (CLAIM_EMPLOYEE, "Employee"),
    (CLAIM_OWNER, "Owner"),
    (CLAIM_ORGANISER, "Event organiser"),
]


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    name = models.CharField(max_length=100, blank=True)
    headline = models.CharField(max_length=180, blank=True)
    location = models.CharField(max_length=100, blank=True)
    skills = models.TextField(blank=True)
    company = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)

    # --- Upgrade path (employee / owner / organiser); optional — general use needs no claim ---
    claim_type = models.CharField(
        max_length=20,
        choices=CLAIM_TYPE_CHOICES,
        default=CLAIM_NONE,
        blank=True,
    )
    owner_cin = models.CharField(max_length=32, blank=True)
    owner_gstin = models.CharField(max_length=32, blank=True)

    # --- Trust tiers (Red → Yellow → Blue → Green); admins toggle verification flags ---
    gov_id = models.FileField(upload_to="verifications/gov_ids/", blank=True, null=True)
    is_gov_id_verified = models.BooleanField(default=False)

    company_email = models.EmailField(blank=True)
    is_company_email_verified = models.BooleanField(default=False)

    is_boss = models.BooleanField(
        default=False,
        help_text="User claims company leadership; Green tier also needs verified company documents.",
    )
    company_docs = models.FileField(upload_to="verifications/company_docs/", blank=True, null=True)
    is_company_verified = models.BooleanField(
        default=False,
        help_text="Admin verified company documents (required for Green tier).",
    )

    # Sandbox identity (Digilocker-style demo) + single product flag for fundraiser + events
    sandbox_verified_at = models.DateTimeField(null=True, blank=True)
    sandbox_reference = models.CharField(max_length=64, blank=True)
    employee_company_confirmed = models.BooleanField(
        default=False,
        help_text="Employer clicked approve link in affiliation email.",
    )
    is_verified_user = models.BooleanField(
        default=False,
        help_text="Verified user: may fundraise and host events (employee/owner/organiser paths).",
    )

    def is_complete(self):
        return all([self.name, self.skills, self.headline, self.location])

    @property
    def trust_tier(self):
        """
        Display tier (emoji). Product access uses `is_verified_user`.
        - Employee: green after employer email approval; yellow/blue after sandbox while pending.
        - Owner / organiser: green when verified on that path (or legacy boss stack).
        """
        if self.claim_type == CLAIM_EMPLOYEE and self.employee_company_confirmed:
            return "green"
        if self.claim_type == CLAIM_EMPLOYEE and self.sandbox_verified_at:
            return "blue" if self.user.trust_score >= 65 else "yellow"

        if self.claim_type == CLAIM_OWNER and self.is_verified_user and self.is_company_verified:
            return "green"
        if self.claim_type == CLAIM_ORGANISER and self.is_verified_user:
            return "green"

        # Legacy rows: verified user before claim_type existed (e.g. admin / migration).
        if self.is_verified_user and self.claim_type in ("", CLAIM_NONE):
            return "green"

        if (
            self.is_boss
            and self.is_company_verified
            and self.is_gov_id_verified
            and self.is_company_email_verified
        ):
            return "green"
        if self.is_company_email_verified and self.is_gov_id_verified:
            return "blue"
        if self.is_gov_id_verified or self.sandbox_verified_at:
            return "yellow"
        return "red"

    @property
    def is_event_organizer(self):
        """True once `EventOrganizerProfile` exists (created when user becomes verified)."""
        return hasattr(self.user, "event_organizer_profile")

    def __str__(self):
        return self.name


class EventOrganizerProfile(models.Model):
    """
    Created when government identity is verified (Digilocker-style / admin-approved gov proof).
    Unlocks hosting events alongside general platform use; optional for users who never verify.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="event_organizer_profile",
    )
    display_name = models.CharField(max_length=200, blank=True)
    public_contact = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.display_name or self.user.username


class EmployeeAffiliationRequest(models.Model):
    """Employer inbox: approve / reject a user's claim they work at `company_name`."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="affiliation_requests")
    company_name = models.CharField(max_length=200)
    company_email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} → {self.company_email} ({self.status})"


class Connection(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ]

    user_from = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_connections')
    user_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_connections')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')

    def __str__(self):
        return f"{self.user_from} -> {self.user_to} ({self.status})"

class Report(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report on {self.user.username}"

