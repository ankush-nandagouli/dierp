import csv
import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from institute.models import Attendance, Batch, CourseTrack, FeeReceipt, StudentAdmission
from institute.utils import generate_receipt_qr

from . import emails, ratelimit, seo
from .forms import (
    PortalAuthenticationForm, ResendVerificationForm, StudentProfileForm, StudentRegistrationForm,
    TrainerProfileForm,
)
from .idcard import id_card_context
from .permissions import get_student, get_trainer, home_url_for, student_required, trainer_required

REG_LIMIT, REG_WINDOW = 5, 60 * 60
RESEND_LIMIT, RESEND_WINDOW = 3, 60 * 60


def _site(request):
    from institute.models import SiteSettings

    return SiteSettings.load()


# =================================================================== public site
def home(request):
    site = _site(request)
    courses = CourseTrack.objects.filter(is_published=True).order_by("code")
    return render(request, "portal/home.html", {
        "courses": courses[:6],
        "ld": seo.dumps([seo.organization(request, site)]),
    })


def course_list(request):
    site = _site(request)
    ld = seo.dumps([seo.breadcrumbs(request, [("Home", "/"), ("Courses", reverse("portal:course_list"))])])
    return render(request, "portal/course_list.html", {
        "courses": CourseTrack.objects.filter(is_published=True).order_by("code"), "ld": ld,
    })


def course_detail(request, slug):
    site = _site(request)
    course = get_object_or_404(CourseTrack, slug=slug, is_published=True)
    ld = seo.dumps([
        seo.course(request, course, site),
        seo.breadcrumbs(request, [("Home", "/"), ("Courses", reverse("portal:course_list")), (course.title, course.get_absolute_url())]),
    ])
    return render(request, "portal/course_detail.html", {
        "course": course,
        "paragraphs": [p.strip() for p in course.description.split("\n\n") if p.strip()],
        "batches": course.batches.filter(is_active=True).select_related("trainer__user"),
        "ld": ld,
    })


def contact(request):
    return render(request, "portal/contact.html")


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/", "Disallow: /accounts/", "Disallow: /dashboard/", "Disallow: /students/",
        "Disallow: /admissions/", "Disallow: /fees/", "Disallow: /kits/", "Disallow: /settings/",
        "Disallow: /student/", "Disallow: /trainer/", "Disallow: /verify/", "Disallow: /verify-id/",
        "Disallow: /verify-email/", "Disallow: /register/done/",
        "",
        f"Sitemap: {request.build_absolute_uri(reverse('portal:sitemap'))}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


# ============================================================ registration & email
def register(request):
    if request.user.is_authenticated:
        return redirect(home_url_for(request.user))
    ip_key = f"register:{ratelimit.client_ip(request)}"
    if request.method == "POST":
        if ratelimit.is_limited(ip_key, REG_LIMIT):
            messages.error(request, "Too many registrations from this network. Please try again in an hour.")
            return render(request, "portal/register.html", {"form": StudentRegistrationForm(request.POST), "noindex": True}, status=429)
        form = StudentRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                student = form.save()
            ratelimit.record(ip_key, REG_WINDOW)
            sent = emails.send_verification_email(request, student.user, _site(request))
            request.session["reg_email"] = student.email
            request.session["reg_email_sent"] = sent
            return redirect("portal:register_done")
    else:
        initial = {}
        slug = request.GET.get("course")
        if slug:
            course = CourseTrack.objects.filter(slug=slug, is_published=True).first()
            if course:
                initial["course"] = course
        form = StudentRegistrationForm(initial=initial)
    return render(request, "portal/register.html", {"form": form})


def register_done(request):
    return render(request, "portal/register_done.html", {
        "email": request.session.get("reg_email", ""),
        "sent": request.session.get("reg_email_sent", True),
    })


def verify_email(request, token):
    try:
        payload = emails.read_verification_token(token)
        student = StudentAdmission.objects.select_related("user").get(user_id=payload["u"])
    except (signing.BadSignature, ObjectDoesNotExist):
        return render(request, "portal/verify_result.html", {"ok": False}, status=400)
    if student.user.email.lower() != payload["e"]:  # email changed after the link was issued
        return render(request, "portal/verify_result.html", {"ok": False}, status=400)
    if not student.email_verified:
        student.email_verified = True
        student.save(update_fields=["email_verified"])
    return render(request, "portal/verify_result.html", {"ok": True})


def resend_verification(request):
    form = ResendVerificationForm(request.POST or None)
    done = False
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        ip_key = f"resend-ip:{ratelimit.client_ip(request)}"
        mail_key = f"resend:{email}"
        if not (ratelimit.is_limited(ip_key, RESEND_LIMIT * 3) or ratelimit.is_limited(mail_key, RESEND_LIMIT)):
            ratelimit.record(ip_key, RESEND_WINDOW)
            ratelimit.record(mail_key, RESEND_WINDOW)
            student = StudentAdmission.objects.select_related("user").filter(
                email__iexact=email, email_verified=False, user__isnull=False
            ).first()
            if student:
                emails.send_verification_email(request, student.user, _site(request))
        done = True  # same answer whether or not the address exists
    return render(request, "portal/resend_verification.html", {"form": form, "done": done, "noindex": True})


# ============================================================= sign in / routing
class SitePasswordResetView(auth_views.PasswordResetView):
    """Password-reset emails can show the center's branding (emails don't run context processors)."""

    @property
    def extra_email_context(self):
        return {"SITE": _site(self.request)}


class PortalLoginView(auth_views.LoginView):
    form_class = PortalAuthenticationForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True


@login_required
def after_login(request):
    return redirect(home_url_for(request.user))


# ============================================================ ID card verification
def verify_id(request, token):
    try:
        student = StudentAdmission.objects.select_related("course", "batch").get(pk=emails.read_id_token(token))
    except (signing.BadSignature, ObjectDoesNotExist):
        return render(request, "portal/verify_id.html", {"student": None}, status=404)
    today = timezone.localdate()
    valid = student.status in ("ACTIVE", "COMPLETED") and student.valid_till >= today
    return render(request, "portal/verify_id.html", {"student": student, "valid": valid})


# ===================================================================== student
@student_required
def student_dashboard(request):
    student = get_student(request.user)
    student = StudentAdmission.objects.select_related("course", "batch__trainer__user").prefetch_related("receipts").get(pk=student.pk)
    return render(request, "portal/student/dashboard.html", {
        "student": student,
        "stats": student.attendance_stats(),
        "recent_attendance": student.attendance.select_related("batch")[:8],
    })


@student_required
def student_receipts(request):
    student = get_student(request.user)
    return render(request, "portal/student/receipts.html", {
        "student": student, "receipts": student.receipts.all(),
    })


@student_required
def student_receipt(request, receipt_id):
    student = get_student(request.user)
    receipt = get_object_or_404(FeeReceipt.objects.select_related("student__course"), pk=receipt_id, student=student)
    return render(request, "portal/student/receipt.html", {
        "receipt": receipt, "student": student, "qr_base64": generate_receipt_qr(request, receipt),
    })


@student_required
def student_profile(request):
    student = get_student(request.user)
    form = StudentProfileForm(request.POST or None, request.FILES or None, instance=student)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been updated.")
        return redirect("portal:student_profile")
    return render(request, "portal/student/profile.html", {"form": form, "student": student})


@student_required
def student_id_card(request):
    student = get_student(request.user)
    if student.status not in ("ACTIVE", "COMPLETED"):
        return render(request, "portal/student/id_card_unavailable.html", {"student": student})
    student = StudentAdmission.objects.select_related("course", "batch").get(pk=student.pk)
    return render(request, "portal/id_card.html", id_card_context(request, student))


# ===================================================================== trainer
def _trainer_batch(request, batch_id):
    return get_object_or_404(
        Batch.objects.select_related("course"), pk=batch_id, trainer=get_trainer(request.user)
    )


@trainer_required
def trainer_dashboard(request):
    trainer = get_trainer(request.user)
    today = timezone.localdate()
    batches = list(trainer.batches.filter(is_active=True).select_related("course"))
    for b in batches:
        b.active_count = b.students.filter(status="ACTIVE").count()
        b.marked_today = b.attendance.filter(date=today).exists()
    return render(request, "portal/trainer/dashboard.html", {"trainer": trainer, "batches": batches, "today": today})


@trainer_required
def trainer_batch(request, batch_id):
    batch = _trainer_batch(request, batch_id)
    students = batch.students.exclude(status__in=["DROPPED", "PENDING"]).order_by("full_name")
    return render(request, "portal/trainer/batch.html", {"batch": batch, "students": students})


def _check_attendance_date(day, batch, site):
    today = timezone.localdate()
    if day > today:
        return "Attendance cannot be marked for a future date."
    if day < batch.start_date:
        return f"This batch started on {batch.start_date:%d %b %Y}; earlier dates are not allowed."
    if (today - day).days > site.trainer_edit_window_days:
        return (f"Trainers can only mark or change attendance within the last {site.trainer_edit_window_days} days. "
                "Ask the administrator to correct older records.")
    return None


@trainer_required
def trainer_attendance(request, batch_id):
    batch = _trainer_batch(request, batch_id)
    site = _site(request)
    today = timezone.localdate()
    day = parse_date(request.POST.get("date") or request.GET.get("date") or "") or today
    students = list(batch.students.filter(status="ACTIVE").order_by("full_name"))
    existing = {a.student_id: a for a in Attendance.objects.filter(batch=batch, date=day)}
    date_error = _check_attendance_date(day, batch, site)
    errors, posted = [], {}

    if request.method == "POST":
        if date_error:
            errors.append(date_error)
        else:
            valid = {code for code, _ in Attendance.STATUS_CHOICES}
            rows = []
            for s in students:
                status = request.POST.get(f"status_{s.pk}", "")
                posted[s.pk] = (status, request.POST.get(f"remarks_{s.pk}", "").strip()[:120])
                if status not in valid:
                    errors.append(f"Select a status for {s.full_name}.")
                rows.append((s, status, posted[s.pk][1]))
            if not students:
                errors.append("There are no active students in this batch.")
            if not errors:
                with transaction.atomic():
                    for s, status, remarks in rows:
                        Attendance.objects.update_or_create(
                            student=s, batch=batch, date=day,
                            defaults={"status": status, "remarks": remarks, "marked_by": request.user},
                        )
                messages.success(request, f"Attendance saved for {day:%A, %d %b %Y}.")
                return redirect(f"{reverse('portal:trainer_attendance', args=[batch.pk])}?date={day.isoformat()}")

    rows = []
    for s in students:
        rec = existing.get(s.pk)
        status, remarks = posted.get(s.pk, (rec.status if rec else "", rec.remarks if rec else ""))
        rows.append({"student": s, "status": status, "remarks": remarks})
    return render(request, "portal/trainer/attendance.html", {
        "batch": batch, "day": day, "rows": rows, "errors": errors or ([date_error] if date_error else []),
        "locked": bool(date_error), "today": today, "choices": Attendance.STATUS_CHOICES,
        "min_date": max(batch.start_date, today - datetime.timedelta(days=site.trainer_edit_window_days)),
    })


@trainer_required
def trainer_report(request, batch_id):
    batch = _trainer_batch(request, batch_id)
    today = timezone.localdate()
    start = parse_date(request.GET.get("from") or "") or today.replace(day=1)
    end = parse_date(request.GET.get("to") or "") or today
    if start > end:
        start, end = end, start
    records = Attendance.objects.filter(batch=batch, date__range=(start, end))
    by_student = {}
    for student_id, status in records.values_list("student_id", "status"):
        by_student.setdefault(student_id, []).append(status)
    rows = []
    for s in batch.students.exclude(status__in=["DROPPED", "PENDING"]).order_by("full_name"):
        sts = by_student.get(s.pk, [])
        p, l, a = sts.count("P"), sts.count("L"), sts.count("A")
        total = p + l + a
        rows.append({"student": s, "present": p, "late": l, "absent": a, "total": total,
                     "percent": round((p + l) * 100 / total) if total else None})
    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="attendance-{batch.pk}-{start}-{end}.csv"'
        w = csv.writer(resp)
        w.writerow(["Enrollment No", "Name", "Present", "Late", "Absent", "Total days", "Attendance %"])
        for r in rows:
            w.writerow([r["student"].enrollment_no, r["student"].full_name, r["present"], r["late"], r["absent"],
                        r["total"], "" if r["percent"] is None else r["percent"]])
        return resp
    return render(request, "portal/trainer/report.html", {"batch": batch, "rows": rows, "start": start, "end": end})


@trainer_required
def trainer_profile(request):
    trainer = get_trainer(request.user)
    form = TrainerProfileForm(request.POST or None, request.FILES or None, instance=trainer)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been updated.")
        return redirect("portal:trainer_profile")
    return render(request, "portal/trainer/profile.html", {"form": form, "trainer": trainer})
