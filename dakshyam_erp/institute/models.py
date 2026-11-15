import os
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator, RegexValidator
from django.db import IntegrityError, models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

indian_mobile = RegexValidator(
    regex=r"^[6-9]\d{9}$",
    message="Enter a valid 10-digit Indian mobile number (no +91 or spaces).",
)


def _next_sequence(model, field, prefix):
    """Return the next integer for numbers shaped like ``<prefix><zero-padded int>``.

    Based on the highest existing number rather than ``count()``, so deleting a
    record never causes a duplicate number to be issued.
    """
    last = (
        model.objects.filter(**{f"{field}__startswith": prefix})
        .order_by(f"-{field}")
        .values_list(field, flat=True)
        .first()
    )
    return int(last[len(prefix):]) + 1 if last else 1


MAX_IMAGE_BYTES = 2 * 1024 * 1024
image_extensions = FileExtensionValidator(["jpg", "jpeg", "png", "webp"])


def validate_image_size(f):
    if f.size > MAX_IMAGE_BYTES:
        raise ValidationError("Image must be 2 MB or smaller.")


def validate_birth_date(value):
    today = timezone.localdate()
    if value > today:
        raise ValidationError("Date of birth cannot be in the future.")
    age = (today - value).days // 365
    if age < 4 or age > 90:
        raise ValidationError("Please enter a realistic date of birth.")


def _random_name(folder, filename):
    ext = os.path.splitext(filename)[1].lower()[:6]
    # Random file names make uploaded photos impossible to guess from a student's name.
    return f"{folder}/{uuid.uuid4().hex}{ext}"


def student_photo_path(instance, filename):
    return _random_name("students/photos", filename)


def trainer_photo_path(instance, filename):
    return _random_name("trainers/photos", filename)


def branding_path(instance, filename):
    return _random_name("branding", filename)


class SiteSettings(models.Model):
    """Single-row table holding the center's branding, contact and SEO defaults."""

    name = models.CharField(max_length=120, default="Dakshyam Innovations")
    tagline = models.CharField(max_length=160, blank=True, default="Learn • Build • Innovate")
    logo = models.ImageField(
        upload_to=branding_path, blank=True, null=True,
        validators=[validate_image_size, image_extensions],
        help_text="PNG, JPG or WEBP, max 2 MB. A square or wide logo on a transparent background works best.",
    )
    phone = models.CharField(max_length=15, blank=True, validators=[indian_mobile])
    email = models.EmailField(blank=True)
    address = models.CharField(
        max_length=250,
        default="Ward No. 4, Siddhivinayak Complex, 1st Floor, Balaghat Road, Waraseoni - 481331 (M.P.)",
    )
    city = models.CharField(max_length=80, default="Waraseoni")
    meta_description = models.CharField(
        max_length=160, blank=True,
        default="Hands-on computer, web development, IoT and robotics training in Waraseoni, Balaghat.",
        help_text="Shown in Google results for the home page (aim for 120-160 characters).",
    )
    show_fees = models.BooleanField(default=False, help_text="Show course fees on the public website.")
    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    google_site_verification = models.CharField(
        max_length=100, blank=True, help_text="Content value of Google Search Console's verification meta tag."
    )
    trainer_edit_window_days = models.PositiveSmallIntegerField(
        default=7, help_text="How many days back a trainer may still change attendance."
    )

    class Meta:
        verbose_name = "Site settings"
        verbose_name_plural = "Site settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton: always the same row
        kwargs.pop("force_insert", None)  # objects.create() must update the existing row, not collide
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # never deleted

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def location_line(self):
        return f"{self.city}, Balaghat, M.P."

    def __str__(self):
        return self.name


class CourseTrack(models.Model):
    TRACK_CHOICES = [
        ("CORE", "01. Core Code: Programming & Logic (C/C++/Python/JS)"),
        ("WEB", "02. Full-Stack Web Development (HTML/CSS/JS/Django/MERN)"),
        ("APP", "03. Mobile App Development (Flutter & Dart)"),
        ("IOT", "04. IoT & Robotics (ESP32, Arduino & Sensors)"),
        ("AI_IOT", "05. Next-Gen: Web Dev + IoT + Applied AI"),
        ("VOC", "06. Vocational Computer Literacy (NEP 2020)"),
    ]
    DURATION_CHOICES = [
        ("1W", "1-Week Bootcamp"),
        ("15D", "15-Day Robotics & Coding Camp"),
        ("3M", "3-Month Core Engineering Track"),
    ]
    code = models.CharField(max_length=10, choices=TRACK_CHOICES, unique=True)
    title = models.CharField(max_length=120)
    duration = models.CharField(max_length=10, choices=DURATION_CHOICES, default="3M")
    total_fee = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    includes_robotics_kit = models.BooleanField(default=False)
    slug = models.SlugField(max_length=140, unique=True, blank=True, null=True, help_text="URL name; auto-generated from the title.")
    summary = models.CharField(max_length=300, blank=True, help_text="One or two sentences shown on course cards and in Google results.")
    description = models.TextField(blank=True, help_text="Full course description / syllabus for the public page. Blank lines separate paragraphs.")
    is_published = models.BooleanField(default=True, help_text="Untick to hide from the website and stop online registration.")

    class Meta:
        ordering = ["code"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:120] or self.code.lower()
            slug, n = base, 2
            while CourseTrack.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        if not self.slug:  # e.g. rows loaded from a fixture or created with bulk_create
            self.save()
        return reverse("portal:course_detail", args=[self.slug])

    @property
    def duration_days(self):
        return {"1W": 7, "15D": 15, "3M": 92}.get(self.duration, 92)

    def __str__(self):
        return f"{self.title} ({self.get_duration_display()})"


class Trainer(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trainer_profile")
    phone = models.CharField(max_length=15, validators=[indian_mobile])
    qualification = models.CharField(max_length=150, blank=True)
    bio = models.TextField(blank=True, max_length=600)
    photo = models.ImageField(
        upload_to=trainer_photo_path, blank=True, null=True,
        validators=[validate_image_size, image_extensions],
    )

    class Meta:
        ordering = ["user__first_name", "user__username"]

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.get_username()

    def __str__(self):
        return self.full_name


class Batch(models.Model):
    """A running class of one course, taught by one trainer."""

    course = models.ForeignKey(CourseTrack, on_delete=models.PROTECT, related_name="batches")
    name = models.CharField(max_length=60, help_text="e.g. Morning A, Weekend 2026")
    timing = models.CharField(max_length=50, default="04:00 PM - 05:30 PM")
    trainer = models.ForeignKey(Trainer, on_delete=models.SET_NULL, null=True, blank=True, related_name="batches")
    start_date = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["course__code", "name"]
        verbose_name_plural = "batches"
        constraints = [models.UniqueConstraint(fields=["course", "name"], name="unique_batch_name_per_course")]

    def __str__(self):
        return f"{self.course.code} · {self.name} ({self.timing})"


class StudentAdmission(models.Model):
    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("COMPLETED", "Completed"),
        ("DROPPED", "Dropped"),
        ("PENDING", "Pending approval"),
    ]
    enrollment_no = models.CharField(max_length=20, unique=True, editable=False)
    full_name = models.CharField(max_length=120)
    guardian_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=15, validators=[indian_mobile])
    whatsapp_no = models.CharField(max_length=15, blank=True, validators=[indian_mobile])
    email = models.EmailField(blank=True)
    school_or_college = models.CharField(max_length=150)
    grade_or_year = models.CharField(max_length=50, help_text="e.g., Class 9, B.Tech 2nd Yr")
    address = models.TextField(default="Waraseoni, Balaghat, M.P.")
    date_of_birth = models.DateField(blank=True, null=True, validators=[validate_birth_date])
    photo = models.ImageField(
        upload_to=student_photo_path, blank=True, null=True,
        validators=[validate_image_size, image_extensions],
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_profile"
    )
    email_verified = models.BooleanField(default=False)
    registered_online = models.BooleanField(default=False)
    batch = models.ForeignKey(Batch, on_delete=models.SET_NULL, null=True, blank=True, related_name="students")

    course = models.ForeignKey(CourseTrack, on_delete=models.PROTECT, related_name="students")
    batch_timing = models.CharField(max_length=50, default="04:00 PM - 05:30 PM")
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0"))]
    )
    admission_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="ACTIVE")
    kit_issued = models.BooleanField(default=False, help_text="ESP32/Arduino Starter Kit Issued")

    class Meta:
        ordering = ["-admission_date", "-id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["admission_date"]),
        ]

    def clean(self):
        super().clean()
        if self.course_id and self.discount_amount is not None and self.discount_amount > self.course.total_fee:
            raise ValidationError({"discount_amount": "Discount cannot exceed the course fee."})
        if self.batch_id and self.course_id and self.batch.course_id != self.course_id:
            raise ValidationError({"batch": "This batch belongs to a different course."})

    def save(self, *args, **kwargs):
        if self.enrollment_no:
            return super().save(*args, **kwargs)
        # Retry on the rare race where two admissions are saved at once.
        for attempt in range(5):
            prefix = f"DI-{timezone.localdate().year}-"
            self.enrollment_no = f"{prefix}{_next_sequence(StudentAdmission, 'enrollment_no', prefix):04d}"
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.enrollment_no = ""
                if attempt == 4:
                    raise

    @property
    def valid_till(self):
        """ID card validity: course length plus a 30-day grace period."""
        return self.admission_date + timedelta(days=self.course.duration_days + 30)

    @property
    def is_minor(self):
        if not self.date_of_birth:
            return False
        return (timezone.localdate() - self.date_of_birth).days // 365 < 18

    def attendance_stats(self):
        records = list(self.attendance.values_list("status", flat=True))
        total = len(records)
        present, late, absent = records.count("P"), records.count("L"), records.count("A")
        pct = round((present + late) * 100 / total) if total else None
        return {"total": total, "present": present, "late": late, "absent": absent, "percent": pct}

    @property
    def net_payable_fee(self):
        return max(self.course.total_fee - self.discount_amount, Decimal("0"))

    @property
    def total_paid(self):
        # Uses prefetched receipts when available (avoids N+1 queries).
        return sum((r.amount_paid for r in self.receipts.all()), Decimal("0"))

    @property
    def balance_due(self):
        return max(self.net_payable_fee - self.total_paid, Decimal("0"))

    def __str__(self):
        return f"{self.enrollment_no} - {self.full_name}"


class FeeReceipt(models.Model):
    PAYMENT_MODES = [
        ("UPI", "UPI / QR Scan"),
        ("CASH", "Cash"),
        ("BANK", "Bank Transfer / NEFT"),
        ("CARD", "Debit / Credit Card"),
    ]
    receipt_no = models.CharField(max_length=25, unique=True, editable=False)
    verification_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    # PROTECT: financial records must never disappear because a student row was deleted.
    student = models.ForeignKey(StudentAdmission, on_delete=models.PROTECT, related_name="receipts")
    amount_paid = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODES, default="UPI")
    transaction_ref = models.CharField(max_length=100, blank=True, help_text="UPI Ref / UTR No.")
    payment_date = models.DateTimeField(default=timezone.now)
    next_due_date = models.DateField(blank=True, null=True)
    remarks = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-payment_date", "-id"]
        indexes = [models.Index(fields=["payment_date"])]

    def save(self, *args, **kwargs):
        if self.receipt_no:
            return super().save(*args, **kwargs)
        for attempt in range(5):
            prefix = f"RCPT-{timezone.localdate().year}-"
            self.receipt_no = f"{prefix}{_next_sequence(FeeReceipt, 'receipt_no', prefix):05d}"
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.receipt_no = ""
                if attempt == 4:
                    raise

    def __str__(self):
        return f"{self.receipt_no} | ₹{self.amount_paid} ({self.student.full_name})"



class Attendance(models.Model):
    PRESENT, ABSENT, LATE = "P", "A", "L"
    STATUS_CHOICES = [(PRESENT, "Present"), (ABSENT, "Absent"), (LATE, "Late")]

    student = models.ForeignKey(StudentAdmission, on_delete=models.CASCADE, related_name="attendance")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="attendance")
    date = models.DateField()
    status = models.CharField(max_length=1, choices=STATUS_CHOICES)
    remarks = models.CharField(max_length=120, blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    marked_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "student__full_name"]
        constraints = [
            models.UniqueConstraint(fields=["student", "batch", "date"], name="one_attendance_per_student_batch_day")
        ]
        indexes = [models.Index(fields=["batch", "date"])]

    def clean(self):
        super().clean()
        if self.date and self.date > timezone.localdate():
            raise ValidationError({"date": "Attendance cannot be marked for a future date."})
        if self.student_id and self.batch_id and self.student.batch_id != self.batch_id:
            raise ValidationError("This student is not enrolled in the selected batch.")

    def __str__(self):
        return f"{self.date} {self.student.full_name}: {self.get_status_display()}"
