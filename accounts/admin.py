from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Profile, Connection, Report


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "name",
        "trust_tier_display",
        "is_gov_id_verified",
        "is_company_email_verified",
        "is_boss",
        "is_company_verified",
    )
    list_filter = ("is_gov_id_verified", "is_company_email_verified", "is_boss", "is_company_verified")
    search_fields = ("user__username", "name", "company_email")
    readonly_fields = ("trust_tier_display",)

    fieldsets = (
        (None, {"fields": ("user", "name", "headline", "location", "skills", "company", "bio")}),
        (
            "Trust tier — government ID (Yellow+)",
            {"fields": ("gov_id", "is_gov_id_verified")},
        ),
        (
            "Work email (Blue+)",
            {"fields": ("company_email", "is_company_email_verified")},
        ),
        (
            "Company leadership (Green)",
            {"fields": ("is_boss", "company_docs", "is_company_verified", "trust_tier_display")},
        ),
    )

    _TIER_EMOJI = {"red": "🔴", "yellow": "🟡", "blue": "🔵", "green": "🟢"}

    @admin.display(description="Tier")
    def trust_tier_display(self, obj):
        if not obj.pk:
            return "—"
        t = obj.trust_tier
        return f"{self._TIER_EMOJI.get(t, '⚪')} {t.capitalize()}"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "full_name", "trust_score", "is_verified_human", "role", "is_staff")
    list_filter = ("role", "is_verified", "is_verified_human", "is_staff", "is_superuser")
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Baadme — trust & role",
            {"fields": ("full_name", "role", "trust_score", "is_verified", "is_verified_human", "is_reported")},
        ),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (None, {"fields": ("full_name", "role")}),
    )


admin.site.register(Connection)
admin.site.register(Report)
