from accounts.models import Profile


def calculate_trust_score(user):
    score = 20


    if user.is_verified:
        score += 30

    if user.is_verified_human:
        score += 20

    try:
        profile = user.profile
    except Profile.DoesNotExist:
        profile = None

    if profile and profile.is_complete():
        score += 20

    # Document-based tier (orthogonal to face verification; boosts score when admins verify)
    if profile:
        tier = profile.trust_tier
        if tier == "yellow":
            score += 5
        elif tier == "blue":
            score += 10
        elif tier == "green":
            score += 15

    connections = user.sent_connections.filter(status='accepted').count()
    if connections >= 5:
        score += 5
    if connections >= 10:
        score += 10

    if user.is_reported:
        score -= 20

    return max(0, min(score, 100))

def update_trust_score(user):
    user.trust_score = calculate_trust_score(user)
    user.save()
