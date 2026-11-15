from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from .models import Attendance, Batch, CourseTrack, FeeReceipt, SiteSettings, StudentAdmission, Trainer

User = get_user_model()


class FeeReceiptInline(admin.TabularInline):
    model = FeeReceipt
    extra = 0
    can_delete = False
    readonly_fields = ("receipt_no", "verification_uuid", "payment_date")
    fields = ("receipt_no", "amount_paid", "payment_mode", "transaction_ref", "payment_date", "next_due_date")


@admin.register(CourseTrack)
class CourseTrackAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "duration", "total_fee", "includes_robotics_kit", "is_published")
    list_editable = ("total_fee", "includes_robotics_kit", "is_published")
    fieldsets = (
        (None, {"fields": ("code", "title", "duration", "total_fee", "includes_robotics_kit")}),
        ("Public website / SEO", {"fields": ("is_published", "slug", "summary", "description")}),
    )
    list_filter = ("duration", "includes_robotics_kit")
    search_fields = ("code", "title")


@admin.register(StudentAdmission)
class StudentAdmissionAdmin(admin.ModelAdmin):
    list_display = (
        "enrollment_no", "full_name", "phone", "course", "batch_timing",
        "status", "batch", "kit_issued", "display_balance_due",
    )
    list_filter = ("status", "course", "batch", "kit_issued", "registered_online", "admission_date")
    actions = ["approve_selected"]
    raw_id_fields = ("user",)
    search_fields = ("enrollment_no", "full_name", "guardian_name", "phone", "school_or_college")
    readonly_fields = ("enrollment_no", "display_net_fee", "display_total_paid", "display_balance_due", "registered_online")
    date_hierarchy = "admission_date"
    list_select_related = ("course",)
    inlines = [FeeReceiptInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("receipts")

    @admin.action(description="Approve selected pending applications")
    def approve_selected(self, request, queryset):
        n = queryset.filter(status="PENDING").update(status="ACTIVE")
        self.message_user(request, f"{n} application(s) approved.", messages.SUCCESS)

    @admin.display(description="Net Payable")
    def display_net_fee(self, obj):
        return f"₹{obj.net_payable_fee}"

    @admin.display(description="Total Paid")
    def display_total_paid(self, obj):
        return f"₹{obj.total_paid}"

    @admin.display(description="Balance Due")
    def display_balance_due(self, obj):
        return f"₹{obj.balance_due}"


@admin.register(FeeReceipt)
class FeeReceiptAdmin(admin.ModelAdmin):
    list_display = ("receipt_no", "student", "amount_paid", "payment_mode", "payment_date", "next_due_date")
    list_filter = ("payment_mode", "payment_date")
    search_fields = ("receipt_no", "student__full_name", "student__enrollment_no", "transaction_ref")
    readonly_fields = ("receipt_no", "verification_uuid")
    list_select_related = ("student",)
    date_hierarchy = "payment_date"

    def has_delete_permission(self, request, obj=None):
        # Issued receipts are an audit trail; correct mistakes with a new entry instead.
        return request.user.is_superuser


admin.site.site_header = "Dakshyam Innovations Administration"
admin.site.site_title = "Dakshyam ERP Admin"
admin.site.index_title = "Center Management Portal"


# ---------------------------------------------------------------- branding
@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    readonly_fields = ("logo_preview",)
    fieldsets = (
        ("Brand", {"fields": ("name", "tagline", "logo", "logo_preview")}),
        ("Contact", {"fields": ("phone", "email", "address", "city")}),
        ("Website & SEO", {"fields": ("meta_description", "show_fees", "google_site_verification",
                                       "facebook_url", "instagram_url", "youtube_url")}),
        ("Attendance", {"fields": ("trainer_edit_window_days",)}),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Current logo")
    def logo_preview(self, obj):
        if obj and obj.logo:
            return format_html('<img src="{}" alt="logo" style="max-height:80px;background:#f1f5f9;padding:6px;border-radius:8px">', obj.logo.url)
        return "No logo uploaded yet"


# ---------------------------------------------------------------- trainers
class TrainerCreateForm(forms.ModelForm):
    """On the 'add' screen this also creates the login account."""

    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(help_text="Used for sign-in and password-reset emails.")
    password = forms.CharField(widget=forms.PasswordInput, strip=False, help_text="The trainer can change it after signing in.")

    class Meta:
        model = Trainer
        exclude = ("user",)

    def clean_username(self):
        name = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=name).exists():
            raise ValidationError("That username is taken.")
        return name

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password"):
            probe = User(username=cleaned.get("username", ""), email=cleaned.get("email", ""))
            try:
                validate_password(cleaned["password"], user=probe)
            except ValidationError as exc:
                self.add_error("password", exc)
        return cleaned


@admin.register(Trainer)
class TrainerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "phone", "active_batches")
    search_fields = ("user__first_name", "user__last_name", "user__username", "user__email", "phone")

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = TrainerCreateForm
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ["username", "first_name", "last_name", "email", "password", "phone", "qualification", "bio", "photo"]
        return ["user", "phone", "qualification", "bio", "photo"]

    def get_readonly_fields(self, request, obj=None):
        return ("user",) if obj else ()

    def save_model(self, request, obj, form, change):
        if not change:
            d = form.cleaned_data
            obj.user = User.objects.create_user(
                username=d["username"], email=d["email"], password=d["password"],
                first_name=d["first_name"], last_name=d.get("last_name", ""),
            )  # is_staff stays False: trainers use the trainer portal, not this admin site
        super().save_model(request, obj, form, change)

    @admin.display(description="Email")
    def email(self, obj):
        return obj.user.email

    @admin.display(description="Active batches")
    def active_batches(self, obj):
        return obj.batches.filter(is_active=True).count()


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("name", "course", "timing", "trainer", "start_date", "is_active", "student_count")
    list_filter = ("course", "trainer", "is_active")
    search_fields = ("name", "course__title", "trainer__user__first_name", "trainer__user__username")
    list_select_related = ("course", "trainer__user")

    @admin.display(description="Students")
    def student_count(self, obj):
        return obj.students.count()


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("date", "student", "batch", "status", "marked_by", "marked_at")
    list_filter = ("status", "batch", "date")
    search_fields = ("student__full_name", "student__enrollment_no")
    date_hierarchy = "date"
    list_select_related = ("student", "batch", "marked_by")
    readonly_fields = ("marked_by", "marked_at")

    def save_model(self, request, obj, form, change):
        obj.marked_by = request.user
        super().save_model(request, obj, form, change)
