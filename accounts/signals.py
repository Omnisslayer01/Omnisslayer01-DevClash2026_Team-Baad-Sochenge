from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, Profile
from .services.trust_service import update_trust_score


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


@receiver(post_save, sender=Profile)
def refresh_trust_when_profile_changes(sender, instance, **kwargs):
    update_trust_score(instance.user)
