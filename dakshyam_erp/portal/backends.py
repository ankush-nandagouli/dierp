from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    """Let people sign in with either their username or their email address."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = (username or kwargs.get(User.USERNAME_FIELD) or "").strip()
        if not identifier or password is None:
            return None
        candidates = User._default_manager.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        ).order_by("id")[:5]
        for user in candidates:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        User().set_password(password)  # equalise timing when nobody matches
        return None
