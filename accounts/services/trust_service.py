def calculate_trust_score(user):
    score = 20


    if user.is_verified:
        score += 30

    if user.is_verified_human:
        score += 20

    if hasattr(user, 'profile') and user.profile.is_complete():
        score += 20

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
