import uuid
from django.db import models
from django.utils import timezone

class CourseTrack(models.Model):
    TRACK_CHOICES = [
        ('CORE', '01. Core Code: Programming & Logic (C/C++/Python/JS)'),
        ('WEB', '02. Full-Stack Web Development (HTML/CSS/JS/Django/MERN)'),
        ('APP', '03. Mobile App Development (Flutter & Dart)'),
        ('IOT', '04. IoT & Robotics (ESP32, Arduino & Sensors)'),
        ('AI_IOT', '05. Next-Gen: Web Dev + IoT + Applied AI'),
        ('VOC', '06. Vocational Computer Literacy (NEP 2020)'),
    ]
    DURATION_CHOICES = [
        ('1W', '1-Week Bootcamp'),
        ('15D', '15-Day Robotics & Coding Camp'),
        ('3M', '3-Month Core Engineering Track'),
    ]
    code = models.CharField(max_length=10, choices=TRACK_CHOICES, unique=True)
    title = models.CharField(max_length=120)
    duration = models.CharField(max_length=10, choices=DURATION_CHOICES, default='3M')
    total_fee = models.DecimalField(max_digits=10, decimal_places=2)
    includes_robotics_kit = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.title} ({self.get_duration_display()})"


class StudentAdmission(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('COMPLETED', 'Completed'),
        ('DROPPED', 'Dropped'),
    ]
    enrollment_no = models.CharField(max_length=20, unique=True, editable=False)
    full_name = models.CharField(max_length=120)
    guardian_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=15)
    whatsapp_no = models.CharField(max_length=15, blank=True)
    email = models.EmailField(blank=True)
    school_or_college = models.CharField(max_length=150)
    grade_or_year = models.CharField(max_length=50, help_text="e.g., Class 9, B.Tech 2nd Yr")
    address = models.TextField(default="Waraseoni, Balaghat, M.P.")
    photo = models.ImageField(upload_to='students/photos/', blank=True, null=True)

    course = models.ForeignKey(CourseTrack, on_delete=models.PROTECT, related_name='students')
    batch_timing = models.CharField(max_length=50, default="04:00 PM - 05:30 PM")
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    admission_date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='ACTIVE')
    kit_issued = models.BooleanField(default=False, help_text="ESP32/Arduino Starter Kit Issued")

    def save(self, *args, **kwargs):
        if not self.enrollment_no:
            year = timezone.now().year
            last_id = StudentAdmission.objects.count() + 1
            self.enrollment_no = f"DI-{year}-{last_id:04d}"
        super().save(*args, **kwargs)

    @property
    def net_payable_fee(self):
        return max(self.course.total_fee - self.discount_amount, 0)

    @property
    def total_paid(self):
        return sum(r.amount_paid for r in self.receipts.all())

    @property
    def balance_due(self):
        return max(self.net_payable_fee - self.total_paid, 0)

    def __str__(self):
        return f"{self.enrollment_no} - {self.full_name}"


class FeeReceipt(models.Model):
    PAYMENT_MODES = [
        ('UPI', 'UPI / QR Scan'),
        ('CASH', 'Cash'),
        ('BANK', 'Bank Transfer / NEFT'),
        ('CARD', 'Debit / Credit Card'),
    ]
    receipt_no = models.CharField(max_length=25, unique=True, editable=False)
    verification_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    student = models.ForeignKey(StudentAdmission, on_delete=models.CASCADE, related_name='receipts')
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODES, default='UPI')
    transaction_ref = models.CharField(max_length=100, blank=True, help_text="UPI Ref / UTR No.")
    payment_date = models.DateTimeField(default=timezone.now)
    next_due_date = models.DateField(blank=True, null=True)
    remarks = models.CharField(max_length=200, blank=True)

    def save(self, *args, **kwargs):
        if not self.receipt_no:
            year = timezone.now().year
            count = FeeReceipt.objects.count() + 1
            self.receipt_no = f"RCPT-{year}-{count:05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.receipt_no} | ₹{self.amount_paid} ({self.student.full_name})"