from django import template

from accounts.models import Profile

register = template.Library()

_TIER_CIRCLE = {
    "red": "🔴",
    "yellow": "🟡",
    "blue": "🔵",
    "green": "🟢",
}


@register.filter
def trust_tier_emoji(tier):
    """Coloured circle emoji for trust tier (red / yellow / blue / green)."""
    if not tier:
        return "⚪"
    return _TIER_CIRCLE.get(str(tier).lower(), "⚪")


@register.simple_tag
def user_trust_emoji(user):
    """Circle emoji from a User (for layouts without `profile` in context)."""
    if not user.is_authenticated:
        return "⚪"
    try:
        tier = user.profile.trust_tier
    except Profile.DoesNotExist:
        return "⚪"
    return _TIER_CIRCLE.get(tier, "⚪")


@register.simple_tag
def user_trust_tier_title(user):
    """Short tooltip text: trust tier name."""
    if not user.is_authenticated:
        return ""
    try:
        t = user.profile.trust_tier
    except Profile.DoesNotExist:
        return "Trust tier: —"
    return f"Trust tier: {t.capitalize()}"
