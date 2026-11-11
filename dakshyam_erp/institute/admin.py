from django.contrib import admin

from .models import CourseTrack, FeeReceipt, StudentAdmission


class FeeReceiptInline(admin.TabularInline):
    model = FeeReceipt
    extra = 0
    can_delete = False
    readonly_fields = ("receipt_no", "verification_uuid", "payment_date")
    fields = ("receipt_no", "amount_paid", "payment_mode", "transaction_ref", "payment_date", "next_due_date")


@admin.register(CourseTrack)
class CourseTrackAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "duration", "total_fee", "includes_robotics_kit")
    list_editable = ("total_fee", "includes_robotics_kit")
    list_filter = ("duration", "includes_robotics_kit")
    search_fields = ("code", "title")


@admin.register(StudentAdmission)
class StudentAdmissionAdmin(admin.ModelAdmin):
    list_display = (
        "enrollment_no", "full_name", "phone", "course", "batch_timing",
        "status", "kit_issued", "display_balance_due",
    )
    list_filter = ("status", "course", "kit_issued", "admission_date")
    search_fields = ("enrollment_no", "full_name", "guardian_name", "phone", "school_or_college")
    readonly_fields = ("enrollment_no", "display_net_fee", "display_total_paid", "display_balance_due")
    date_hierarchy = "admission_date"
    list_select_related = ("course",)
    inlines = [FeeReceiptInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("receipts")

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