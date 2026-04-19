from __future__ import annotations

from rest_framework.permissions import BasePermission, SAFE_METHODS

from events_api import services


class IsVerifiedIdentityForEventCreate(BasePermission):
    """BLUE/GREEN badge or id_verified (gov) — required only for creating platform events."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if getattr(view, "action", None) != "create":
            return bool(request.user and request.user.is_authenticated)
        if not request.user or not request.user.is_authenticated:
            return False
        return services.organizer_identity_allowed_for_events(request.user)


class IsOrganizerOrReadOnly(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return getattr(obj, "organizer_id", None) == request.user.id
