import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import IntegrityError, models, transaction
from django.utils import timezone

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

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.title} ({self.get_duration_display()})"


class StudentAdmission(models.Model):
    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("COMPLETED", "Completed"),
        ("DROPPED", "Dropped"),
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
    photo = models.ImageField(upload_to="students/photos/", blank=True, null=True)

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