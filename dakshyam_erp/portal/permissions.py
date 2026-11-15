from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse

from institute.decorators import role_required


def get_trainer(user):
    if not (user.is_authenticated and user.is_active):
        return None
    try:
        return user.trainer_profile
    except ObjectDoesNotExist:
        return None


def get_student(user):
    if not (user.is_authenticated and user.is_active):
        return None
    try:
        profile = user.student_profile
    except ObjectDoesNotExist:
        return None
    return profile if profile.email_verified else None


def home_url_for(user):
    """Where each kind of account lands after signing in."""
    if user.is_authenticated and user.is_active:
        if user.is_staff:
            return reverse("dashboard")
        if get_trainer(user):
            return reverse("portal:trainer_dashboard")
        if get_student(user):
            return reverse("portal:student_dashboard")
    return reverse("portal:home")


student_required = role_required(lambda u: get_student(u) is not None)
trainer_required = role_required(lambda u: get_trainer(u) is not None)
