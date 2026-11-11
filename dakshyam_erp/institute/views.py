import csv
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import AdmissionForm, FeeReceiptForm
from .models import CourseTrack, FeeReceipt, StudentAdmission
from .utils import generate_receipt_qr


# ---------------------------------------------------------------- dashboard
@login_required
def dashboard(request):
    today = timezone.localdate()
    receipts = FeeReceipt.objects.all()
    # One query for students + one for their receipts, no per-row queries.
    open_students = (
        StudentAdmission.objects.exclude(status="DROPPED")
        .select_related("course")
        .prefetch_related("receipts")
    )
    context = {
        "total_students": StudentAdmission.objects.filter(status="ACTIVE").count(),
        "total_collected": receipts.aggregate(t=Sum("amount_paid"))["t"] or Decimal("0"),
        "month_collected": receipts.filter(
            payment_date__year=today.year, payment_date__month=today.month
        ).aggregate(t=Sum("amount_paid"))["t"] or Decimal("0"),
        "total_pending": sum((s.balance_due for s in open_students), Decimal("0")),
        "recent_receipts": receipts.select_related("student", "student__course")[:6],
        "courses": CourseTrack.objects.all(),
    }
    return render(request, "dashboard.html", context)


# --------------------------------------------------------------- admissions
@login_required
def create_admission(request):
    form = AdmissionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        student = form.save()
        messages.success(request, f"Admission confirmed! Enrollment ID: {student.enrollment_no}")
        return redirect("collect_fee", student_id=student.id)
    return render(request, "admissions/admission_form.html", {"form": form, "editing": False})


@login_required
def edit_admission(request, student_id):
    student = get_object_or_404(StudentAdmission, id=student_id)
    form = AdmissionForm(request.POST or None, request.FILES or None, instance=student)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Updated record for {student.full_name}.")
        return redirect("student_detail", student_id=student.id)
    return render(
        request, "admissions/admission_form.html", {"form": form, "editing": True, "student": student}
    )


@login_required
def student_detail(request, student_id):
    student = get_object_or_404(
        StudentAdmission.objects.select_related("course").prefetch_related("receipts"), id=student_id
    )
    return render(request, "admissions/student_detail.html", {"student": student})


def _filtered_students(request):
    query = request.GET.get("q", "").strip()
    track_filter = request.GET.get("track", "").strip()
    fee_filter = request.GET.get("fee", "").strip()

    students = StudentAdmission.objects.select_related("course").prefetch_related("receipts")
    if query:
        students = students.filter(
            Q(full_name__icontains=query)
            | Q(enrollment_no__icontains=query)
            | Q(phone__icontains=query)
            | Q(school_or_college__icontains=query)
        )
    if track_filter:
        students = students.filter(course__code=track_filter)

    student_list = list(students)
    if fee_filter == "due":
        student_list = [s for s in student_list if s.balance_due > 0]
    elif fee_filter == "paid":
        student_list = [s for s in student_list if s.balance_due == 0]
    return student_list, track_filter, fee_filter


@login_required
def student_directory(request):
    student_list, track_filter, fee_filter = _filtered_students(request)
    context = {
        "students": student_list,
        "courses": CourseTrack.objects.all(),
        "selected_track": track_filter,
        "selected_fee": fee_filter,
    }
    if request.headers.get("HX-Request"):
        return render(request, "admissions/partials/student_rows.html", context)
    return render(request, "admissions/student_list.html", context)


def _csv_safe(value):
    """Neutralise spreadsheet formula injection (=, +, -, @ at the start of a cell)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@login_required
def export_students_csv(request):
    student_list, _, _ = _filtered_students(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="students-{timezone.localdate()}.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "Enrollment No", "Name", "Guardian", "Phone", "School/College", "Course",
        "Batch", "Status", "Net Fee", "Paid", "Balance Due", "Admission Date",
    ])
    for s in student_list:
        writer.writerow([
            _csv_safe(v) for v in (
                s.enrollment_no, s.full_name, s.guardian_name, s.phone, s.school_or_college,
                s.course.title, s.batch_timing, s.get_status_display(), s.net_payable_fee,
                s.total_paid, s.balance_due, s.admission_date.isoformat(),
            )
        ])
    return response


# --------------------------------------------------------------------- kits
@login_required
def kit_tracker(request):
    students = StudentAdmission.objects.select_related("course").prefetch_related("receipts").filter(
        Q(course__includes_robotics_kit=True) | Q(kit_issued=True)
    ).order_by("kit_issued", "-admission_date")
    issued_count = sum(1 for s in students if s.kit_issued)
    return render(request, "academics/kit_tracker.html", {
        "students": students,
        "issued_count": issued_count,
        "pending_count": len(students) - issued_count,
    })


@login_required
@require_POST
def toggle_kit_status(request, student_id):
    student = get_object_or_404(StudentAdmission, id=student_id)
    student.kit_issued = not student.kit_issued
    student.save(update_fields=["kit_issued"])
    return render(request, "academics/partials/kit_badge.html", {"student": student})


# ------------------------------------------------------------------ billing
@login_required
def collect_fee(request, student_id):
    student = get_object_or_404(StudentAdmission.objects.select_related("course"), id=student_id)
    if student.balance_due == 0:
        messages.info(request, f"{student.full_name} has no outstanding balance.")
        return redirect("student_detail", student_id=student.id)

    if request.method == "POST":
        form = FeeReceiptForm(request.POST, student=student)
        if form.is_valid():
            receipt = form.save(commit=False)
            receipt.student = student
            receipt.save()
            messages.success(request, f"Receipt {receipt.receipt_no} generated!")
            return redirect("view_receipt", receipt_id=receipt.id)
    else:
        form = FeeReceiptForm(initial={"amount_paid": student.balance_due}, student=student)
    return render(request, "billing/collect_fee.html", {"student": student, "form": form})


@login_required
def receipt_list(request):
    query = request.GET.get("q", "").strip()
    receipts = FeeReceipt.objects.select_related("student", "student__course")
    if query:
        receipts = receipts.filter(
            Q(receipt_no__icontains=query)
            | Q(student__full_name__icontains=query)
            | Q(student__enrollment_no__icontains=query)
            | Q(transaction_ref__icontains=query)
        )
    page = Paginator(receipts, 25).get_page(request.GET.get("page"))
    total = receipts.aggregate(t=Sum("amount_paid"))["t"] or Decimal("0")
    return render(request, "billing/receipt_list.html", {"page": page, "query": query, "total": total})


@login_required
def view_receipt(request, receipt_id):
    receipt = get_object_or_404(
        FeeReceipt.objects.select_related("student", "student__course"), id=receipt_id
    )
    return render(request, "billing/receipt_print.html", {
        "receipt": receipt,
        "qr_base64": generate_receipt_qr(request, receipt),
    })


def verify_receipt(request, verification_uuid):
    """Public page opened by scanning the receipt QR code (UUID is the credential)."""
    receipt = get_object_or_404(
        FeeReceipt.objects.select_related("student", "student__course"),
        verification_uuid=verification_uuid,
    )
    return render(request, "billing/verify_receipt.html", {"receipt": receipt})


# ------------------------------------------------------------ error pages
def handler404(request, exception=None):
    return render(request, "404.html", status=404)


def handler500(request):
    return render(request, "500.html", status=500)