from rest_framework import permissions


class UpdateOwnProfile(permissions.BasePermission):
    """Deny anonymous access. Creation is staff-only. Writes stay owner-only."""

    def has_permission(self, request, view):
        try:
            user = request.user
            if user is None or not user.is_authenticated:
                return False
            if request.method == "POST":
                return bool(user.is_staff or user.is_superuser)
            return True
        except Exception:
            return False

    def has_object_permission(self, request, view, obj):
        try:
            user = request.user
            if user is None or not user.is_authenticated:
                return False
            if request.method in permissions.SAFE_METHODS:
                return True
            return obj.id == user.id
        except Exception:
            return False
