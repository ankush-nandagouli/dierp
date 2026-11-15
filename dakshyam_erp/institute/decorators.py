from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def role_required(check):
    """Anonymous -> login page. Logged in but wrong role -> 403 (never a login loop)."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not check(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def _is_staff(user):
    return user.is_active and user.is_staff


def _is_superuser(user):
    return user.is_active and user.is_superuser


staff_required = role_required(_is_staff)
superuser_required = role_required(_is_superuser)
