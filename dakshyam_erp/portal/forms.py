import unicodedata

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from institute.forms import TailwindFormMixin  # noqa: F401  (kept for staff forms)
from institute.models import (
    Batch, CourseTrack, StudentAdmission, Trainer, image_extensions, indian_mobile,
    validate_birth_date, validate_image_size,
)

from . import ratelimit

User = get_user_model()
LOGIN_LIMIT, LOGIN_WINDOW = 10, 15 * 60


def validate_person_name(value):
    value = value.strip()
    if len(value) < 2:
        raise ValidationError("Please enter the full name.")
    for ch in value:
        cat = unicodedata.category(ch)
        if not (cat[0] in ("L", "M") or ch in " .'-"):
            raise ValidationError("Names may contain only letters, spaces, dots, apostrophes and hyphens.")


class BatchChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.course.title} - {obj.name} ({obj.timing})"


class CssForm:
    """Adds the site's CSS classes to widgets (used with templates/portal/_field.html)."""

    def style_widgets(self):
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("class", "check")
            elif isinstance(w, forms.HiddenInput):
                continue
            else:
                w.attrs.setdefault("class", "input")
            if field.required and not isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("required", "required")


# ------------------------------------------------------------------ registration
class StudentRegistrationForm(CssForm, forms.Form):
    full_name = forms.CharField(max_length=120, validators=[validate_person_name])
    date_of_birth = forms.DateField(
        validators=[validate_birth_date], widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    guardian_name = forms.CharField(max_length=120, label="Parent / guardian name", validators=[validate_person_name])
    phone = forms.CharField(max_length=10, label="Mobile number", validators=[indian_mobile],
                            widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "10-digit mobile"}))
    whatsapp_no = forms.CharField(max_length=10, required=False, label="WhatsApp number (optional)",
                                  validators=[indian_mobile], widget=forms.TextInput(attrs={"inputmode": "numeric"}))
    email = forms.EmailField(max_length=254, help_text="We email a confirmation link to this address; you will also sign in with it.")
    school_or_college = forms.CharField(max_length=150, label="School / college")
    grade_or_year = forms.CharField(max_length=50, label="Class / year", widget=forms.TextInput(attrs={"placeholder": "e.g. Class 10, B.Sc 2nd year"}))
    address = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 2}))
    course = forms.ModelChoiceField(queryset=CourseTrack.objects.none(), empty_label="Select a course")
    batch = BatchChoiceField(queryset=Batch.objects.none(), required=False, empty_label="No preference", label="Preferred batch (optional)")
    photo = forms.ImageField(required=False, label="Passport-size photo (optional)",
                             validators=[validate_image_size, image_extensions],
                             help_text="JPG, PNG or WEBP, up to 2 MB. Used on your ID card.")
    password1 = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirm password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    accept_terms = forms.BooleanField(
        label="I confirm the details are correct, and (if under 18) that my parent/guardian agrees to this registration.",
        error_messages={"required": "You must accept this to register."},
    )
    # Honeypot: real visitors never see or fill this; bots usually do.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = CourseTrack.objects.filter(is_published=True).order_by("code")
        self.fields["batch"].queryset = (
            Batch.objects.filter(is_active=True, course__is_published=True).select_related("course")
        )
        self.style_widgets()
        self.fields["website"].widget.attrs["class"] = "hp-field"
        self.fields["website"].widget.attrs.pop("required", None)

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise ValidationError("Invalid submission.")
        return ""

    def clean_full_name(self):
        return " ".join(self.cleaned_data["full_name"].split())

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            raise ValidationError("An account with this email already exists. Sign in or reset your password instead.")
        if StudentAdmission.objects.filter(email__iexact=email).exists():
            raise ValidationError("This email already has an admission record. Please contact the center to activate portal access.")
        return email

    def clean_whatsapp_no(self):
        return self.cleaned_data.get("whatsapp_no") or self.cleaned_data.get("phone", "")

    def clean(self):
        cleaned = super().clean()
        course, batch = cleaned.get("course"), cleaned.get("batch")
        if course and batch and batch.course_id != course.id:
            self.add_error("batch", "This batch does not belong to the selected course.")
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        elif p1:
            probe = User(username=cleaned.get("email", ""), email=cleaned.get("email", ""),
                         first_name=(cleaned.get("full_name") or "").split(" ")[0])
            try:
                validate_password(p1, user=probe)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self):
        d = self.cleaned_data
        user = User.objects.create_user(
            username=d["email"], email=d["email"], password=d["password1"],
            first_name=d["full_name"].split(" ")[0][:150], last_name=" ".join(d["full_name"].split(" ")[1:])[:150],
        )
        student = StudentAdmission.objects.create(
            user=user, status="PENDING", registered_online=True, email_verified=False,
            full_name=d["full_name"], date_of_birth=d["date_of_birth"], guardian_name=d["guardian_name"],
            phone=d["phone"], whatsapp_no=d["whatsapp_no"], email=d["email"],
            school_or_college=d["school_or_college"], grade_or_year=d["grade_or_year"],
            address=d["address"], photo=d.get("photo"), course=d["course"], batch=d.get("batch"),
            admission_date=timezone.localdate(),
        )
        return student


# ------------------------------------------------------------------ login
class PortalAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Email or username", widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}))
    unverified = False

    def _key(self):
        ident = (self.data.get("username") or "").strip().lower()[:100]
        return f"login:{ratelimit.client_ip(self.request)}:{ident}"

    def clean(self):
        key = self._key()
        if ratelimit.is_limited(key, LOGIN_LIMIT):
            raise ValidationError("Too many failed attempts. Please wait 15 minutes and try again.", code="throttled")
        try:
            cleaned = super().clean()
        except ValidationError:
            ratelimit.record(key, LOGIN_WINDOW)
            raise
        ratelimit.reset(key)
        return cleaned

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        profile = getattr(user, "student_profile", None)
        if profile is not None and not profile.email_verified:
            self.unverified = True
            raise ValidationError(
                "Please confirm your email address first. We sent you a link; you can request a new one below.",
                code="unverified",
            )


class ResendVerificationForm(forms.Form):
    email = forms.EmailField()


# ------------------------------------------------------------------ profiles
class StudentProfileForm(CssForm, forms.ModelForm):
    class Meta:
        model = StudentAdmission
        fields = ["guardian_name", "phone", "whatsapp_no", "date_of_birth", "school_or_college",
                  "grade_or_year", "address", "photo"]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "address": forms.Textarea(attrs={"rows": 2}),
            "photo": forms.FileInput,
        }
        labels = {"whatsapp_no": "WhatsApp number", "school_or_college": "School / college", "grade_or_year": "Class / year"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_widgets()
        self.fields["whatsapp_no"].required = False

    def clean_guardian_name(self):
        validate_person_name(self.cleaned_data["guardian_name"])
        return " ".join(self.cleaned_data["guardian_name"].split())

    def clean_whatsapp_no(self):
        return self.cleaned_data.get("whatsapp_no") or self.cleaned_data.get("phone", "")


class TrainerProfileForm(CssForm, forms.ModelForm):
    first_name = forms.CharField(max_length=150, validators=[validate_person_name])
    last_name = forms.CharField(max_length=150, required=False)

    class Meta:
        model = Trainer
        fields = ["phone", "qualification", "bio", "photo"]
        widgets = {"bio": forms.Textarea(attrs={"rows": 4}), "photo": forms.FileInput}

    field_order = ["first_name", "last_name", "phone", "qualification", "bio", "photo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].initial = self.instance.user.first_name
        self.fields["last_name"].initial = self.instance.user.last_name
        self.style_widgets()

    def save(self, commit=True):
        trainer = super().save(commit=False)
        trainer.user.first_name = self.cleaned_data["first_name"]
        trainer.user.last_name = self.cleaned_data["last_name"]
        if commit:
            trainer.user.save(update_fields=["first_name", "last_name"])
            trainer.save()
        return trainer
