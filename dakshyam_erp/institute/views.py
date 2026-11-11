from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.contrib import messages
from .models import StudentAdmission, FeeReceipt, CourseTrack
from .forms import AdmissionForm, FeeReceiptForm
import io
import base64
import qrcode
from django.http import HttpResponse
from django.views.decorators.http import require_POST
# Ensure Q, StudentAdmission, FeeReceipt, CourseTrack are imported from earlier

@login_required
def dashboard(request):
    total_students = StudentAdmission.objects.filter(status='ACTIVE').count()
    total_collected = FeeReceipt.objects.aggregate(total=Sum('amount_paid'))['total'] or 0
    students = StudentAdmission.objects.select_related('course').all()
    total_pending = sum(s.balance_due for s in students)
    recent_receipts = FeeReceipt.objects.select_related('student', 'student__course').order_by('-payment_date')[:6]

    context = {
        'total_students': total_students,
        'total_collected': total_collected,
        'total_pending': total_pending,
        'recent_receipts': recent_receipts,
        'courses': CourseTrack.objects.all(),
    }
    return render(request, 'dashboard.html', context)

@login_required
def create_admission(request):
    if request.method == 'POST':
        form = AdmissionForm(request.POST, request.FILES)
        if form.is_valid():
            student = form.save()
            messages.success(request, f"Admission confirmed! Enrollment ID: {student.enrollment_no}")
            return redirect('collect_fee', student_id=student.id)
    else:
        form = AdmissionForm()
    return render(request, 'admissions/admission_form.html', {'form': form})

@login_required
def collect_fee(request, student_id):
    student = get_object_or_404(StudentAdmission, id=student_id)
    if request.method == 'POST':
        form = FeeReceiptForm(request.POST)
        if form.is_valid():
            receipt = form.save(commit=False)
            receipt.student = student
            receipt.save()
            messages.success(request, f"Receipt {receipt.receipt_no} generated!")
            return redirect('view_receipt', receipt_id=receipt.id)
    else:
        form = FeeReceiptForm(initial={'amount_paid': student.balance_due})
    return render(request, 'billing/collect_fee.html', {'student': student, 'form': form})

def view_receipt(request, receipt_id):
    receipt = get_object_or_404(FeeReceipt.objects.select_related('student', 'student__course'), id=receipt_id)
    return render(request, 'billing/receipt_print.html', {'receipt': receipt})


@login_required
def student_directory(request):
    query = request.GET.get("q", "").strip()
    track_filter = request.GET.get("track", "").strip()
    fee_filter = request.GET.get("fee", "").strip()

    students = StudentAdmission.objects.select_related("course").prefetch_related("receipts").order_by("-admission_date", "-id")

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

    context = {
        "students": student_list,
        "courses": CourseTrack.objects.all(),
        "selected_track": track_filter,
        "selected_fee": fee_filter,
    }

    if request.headers.get("HX-Request"):
        return render(request, "admissions/partials/student_rows.html", context)
    return render(request, "admissions/student_list.html", context)


@login_required
def kit_tracker(request):
    students = StudentAdmission.objects.select_related("course").filter(
        Q(course__includes_robotics_kit=True) | Q(kit_issued=True)
    ).order_by("kit_issued", "-admission_date")

    issued_count = students.filter(kit_issued=True).count()
    pending_count = students.filter(kit_issued=False).count()

    return render(request, "academics/kit_tracker.html", {
        "students": students,
        "issued_count": issued_count,
        "pending_count": pending_count,
    })


@login_required
@require_POST
def toggle_kit_status(request, student_id):
    student = get_object_or_404(StudentAdmission, id=student_id)
    student.kit_issued = not student.kit_issued
    student.save(update_fields=["kit_issued"])
    return render(request, "academics/partials/kit_badge.html", {"student": student})


def verify_receipt(request, verification_uuid):
    """Public verification page opened by scanning the receipt QR code."""
    receipt = get_object_or_404(
        FeeReceipt.objects.select_related("student", "student__course"),
        verification_uuid=verification_uuid,
    )
    return render(request, "billing/verify_receipt.html", {"receipt": receipt})

from .utils import generate_receipt_qr

def view_receipt(request, receipt_id):
    receipt = get_object_or_404(FeeReceipt.objects.select_related("student", "student__course"), id=receipt_id)
    qr_base64 = generate_receipt_qr(request, receipt)
    return render(request, "billing/receipt_print.html", {"receipt": receipt, "qr_base64": qr_base64})