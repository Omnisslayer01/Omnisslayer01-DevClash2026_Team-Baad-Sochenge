from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, Profile, EventOrganizerProfile
from .services.trust_service import update_trust_score


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


@receiver(post_save, sender=Profile)
def refresh_trust_when_profile_changes(sender, instance, **kwargs):
    update_trust_score(instance.user)


@receiver(post_save, sender=Profile)
def create_event_organizer_when_verified_user(sender, instance, **kwargs):
    """Verified users may fundraise and host events; provision organizer row once."""
    if instance.is_verified_user:
        EventOrganizerProfile.objects.get_or_create(
            user=instance.user,
            defaults={"display_name": instance.name or instance.user.username},
        )
