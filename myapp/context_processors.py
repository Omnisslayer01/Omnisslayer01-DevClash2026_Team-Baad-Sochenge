from events_api import wallet_services
from events_api.models import UserWallet


def wallet_nav(request):
    ctx = {"wallet_balance": None, "wallet_eligible": False}
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return ctx
    ctx["wallet_eligible"] = wallet_services.user_may_use_wallet(user)
    if not ctx["wallet_eligible"]:
        return ctx
    w = UserWallet.objects.filter(user=user).only("balance").first()
    if w is not None:
        ctx["wallet_balance"] = str(w.balance)
    return ctx
