import logging

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.core import signing
from django.core.mail import send_mail
from django.urls import reverse

from institute.models import SiteSettings

logger = logging.getLogger(__name__)
VERIFY_SALT = "portal.email-verification"
ID_SALT = "portal.id-card"


# ---- signed, expiring tokens (nothing is stored in the database) ----
def make_verification_token(user):
    return signing.dumps({"u": user.pk, "e": user.email.lower()}, salt=VERIFY_SALT)


def read_verification_token(token):
    """Return the payload, or raise signing.BadSignature / SignatureExpired."""
    return signing.loads(token, salt=VERIFY_SALT, max_age=settings.EMAIL_VERIFICATION_MAX_AGE)


def make_id_token(student):
    return signing.dumps(student.pk, salt=ID_SALT)


def read_id_token(token):
    return signing.loads(token, salt=ID_SALT)


# ---- messages ----
def _send(subject, body, to):
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
        return True
    except Exception:  # SMTP down / misconfigured: never crash the request
        logger.exception("Could not send email to %s", to)
        return False


def send_verification_email(request, user, site):
    link = request.build_absolute_uri(reverse("portal:verify_email", args=[make_verification_token(user)]))
    hours = settings.EMAIL_VERIFICATION_MAX_AGE // 3600
    body = (
        f"Hello {user.first_name or 'there'},\n\n"
        f"Thank you for registering with {site.name}. Please confirm your email address by opening this link:\n\n"
        f"{link}\n\n"
        f"The link is valid for {hours} hours. If you did not register, you can ignore this email.\n\n"
        f"- {site.name}"
    )
    return _send(f"Confirm your email - {site.name}", body, user.email)


def send_admission_confirmed_email(request, student, site):
    if not (student.user and student.user.email):
        return False
    link = request.build_absolute_uri(reverse("portal:student_dashboard"))
    body = (
        f"Hello {student.full_name},\n\n"
        f"Your admission to {student.course.title} is confirmed. Your enrollment number is {student.enrollment_no}.\n"
        f"Sign in to view your course details, fee receipts and ID card: {link}\n\n- {site.name}"
    )
    return _send(f"Admission confirmed - {site.name}", body, student.user.email)


def send_set_password_email(request, user):
    """Emails a one-time 'set your password' link (used when staff create a portal login)."""
    form = PasswordResetForm({"email": user.email})
    if not form.is_valid():
        return False
    try:
        form.save(
            request=request,
            use_https=request.is_secure(),
            from_email=settings.DEFAULT_FROM_EMAIL,
            subject_template_name="registration/password_reset_subject.txt",
            email_template_name="registration/password_reset_email.html",
            extra_email_context={"SITE": SiteSettings.load()},
        )
        return True
    except Exception:
        logger.exception("Could not send set-password email to %s", user.email)
        return False
