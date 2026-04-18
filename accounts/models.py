
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

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    name = models.CharField(max_length=100, blank=True)
    headline = models.CharField(max_length=180, blank=True)
    location = models.CharField(max_length=100, blank=True)
    skills = models.TextField(blank=True)
    company = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)

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

    def is_complete(self):
        return all([self.name, self.skills, self.headline, self.location])

    @property
    def trust_tier(self):
        """
        Derived rank: green > blue > yellow > red.
        Green: Yellow+Blue requirements, plus boss flag and admin-verified company documents.
        Blue: gov ID verified + work email verified by org.
        Yellow: gov ID verified only.
        Red: default (most users).
        """
        if (
            self.is_boss
            and self.is_company_verified
            and self.is_gov_id_verified
            and self.is_company_email_verified
        ):
            return "green"
        if self.is_company_email_verified and self.is_gov_id_verified:
            return "blue"
        if self.is_gov_id_verified:
            return "yellow"
        return "red"

    def __str__(self):
        return self.name

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

