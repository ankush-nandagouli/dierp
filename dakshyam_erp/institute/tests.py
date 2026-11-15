import csv
import io
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from .forms import AdmissionForm, FeeReceiptForm
from .models import CourseTrack, FeeReceipt, StudentAdmission


def make_course(code="IOT", fee="10000", kit=True):
    return CourseTrack.objects.create(
        code=code, title=f"Track {code}", duration="3M", total_fee=Decimal(fee), includes_robotics_kit=kit
    )


def make_student(course=None, **kw):
    defaults = dict(
        full_name="Aarav Sharma", guardian_name="R Sharma", phone="9876543210",
        school_or_college="KV", grade_or_year="Class 10", course=course or make_course(),
    )
    defaults.update(kw)
    return StudentAdmission.objects.create(**defaults)


class ModelTests(TestCase):
    def test_enrollment_numbers_are_sequential_and_unique_after_delete(self):
        c = make_course()
        a = make_student(c)
        b = make_student(c, full_name="B")
        self.assertNotEqual(a.enrollment_no, b.enrollment_no)
        a_no, b_no = a.enrollment_no, b.enrollment_no
        a.delete()  # a count()-based generator would now re-issue b's number
        n = make_student(c, full_name="C")
        self.assertNotIn(n.enrollment_no, {a_no, b_no})
        self.assertRegex(b_no, r"^DI-\d{4}-0002$")

    def test_fee_math(self):
        s = make_student(make_course(fee="10000"), discount_amount=Decimal("1000"))
        self.assertEqual(s.net_payable_fee, Decimal("9000"))
        FeeReceipt.objects.create(student=s, amount_paid=Decimal("2500"), payment_mode="CASH")
        FeeReceipt.objects.create(student=s, amount_paid=Decimal("500"), payment_mode="CASH")
        s = StudentAdmission.objects.get(pk=s.pk)
        self.assertEqual(s.total_paid, Decimal("3000"))
        self.assertEqual(s.balance_due, Decimal("6000"))

    def test_discount_cannot_exceed_fee(self):
        s = make_student(make_course(fee="1000"), discount_amount=Decimal("2000"))
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_receipt_numbers_unique_and_uuid_set(self):
        s = make_student()
        r1 = FeeReceipt.objects.create(student=s, amount_paid=1, payment_mode="CASH")
        r2 = FeeReceipt.objects.create(student=s, amount_paid=1, payment_mode="CASH")
        self.assertNotEqual(r1.receipt_no, r2.receipt_no)
        self.assertNotEqual(r1.verification_uuid, r2.verification_uuid)

    def test_student_with_receipts_cannot_be_deleted(self):
        s = make_student()
        FeeReceipt.objects.create(student=s, amount_paid=100, payment_mode="CASH")
        with self.assertRaises(ProtectedError):
            s.delete()


class FormTests(TestCase):
    def test_phone_validation(self):
        c = make_course()
        data = dict(
            full_name="X", guardian_name="Y", phone="12345", school_or_college="S", grade_or_year="9",
            address="a", course=c.pk, status="ACTIVE", batch_timing="4pm", discount_amount="0", admission_date="2026-01-01",
        )
        self.assertIn("phone", AdmissionForm(data).errors)
        data["phone"] = "9876543210"
        form = AdmissionForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["whatsapp_no"], "9876543210")  # defaults to phone

    def test_overpayment_rejected(self):
        s = make_student(make_course(fee="1000"))
        form = FeeReceiptForm({"amount_paid": "1500", "payment_mode": "CASH"}, student=s)
        self.assertIn("amount_paid", form.errors)

    def test_non_cash_requires_reference(self):
        s = make_student(make_course(fee="1000"))
        form = FeeReceiptForm({"amount_paid": "500", "payment_mode": "UPI"}, student=s)
        self.assertIn("transaction_ref", form.errors)
        ok = FeeReceiptForm({"amount_paid": "500", "payment_mode": "UPI", "transaction_ref": "UTR1"}, student=s)
        self.assertTrue(ok.is_valid(), ok.errors)


class ViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("staff", password="pw-12345-xyz", is_staff=True)
        cls.course = make_course(fee="10000")
        cls.student = make_student(cls.course)

    def login(self):
        self.client.login(username="staff", password="pw-12345-xyz")

    def test_all_internal_pages_require_login(self):
        receipt = FeeReceipt.objects.create(student=self.student, amount_paid=100, payment_mode="CASH")
        urls = [
            reverse("dashboard"), reverse("create_admission"), reverse("student_directory"),
            reverse("export_students"), reverse("kit_tracker"), reverse("receipt_list"),
            reverse("student_detail", args=[self.student.pk]), reverse("edit_admission", args=[self.student.pk]),
            reverse("collect_fee", args=[self.student.pk]), reverse("view_receipt", args=[receipt.pk]),
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn("/accounts/login/", resp["Location"], url)

    def test_pages_render_when_logged_in(self):
        self.login()
        receipt = FeeReceipt.objects.create(student=self.student, amount_paid=100, payment_mode="CASH")
        for url in [
            reverse("dashboard"), reverse("create_admission"), reverse("student_directory"),
            reverse("kit_tracker"), reverse("receipt_list"),
            reverse("student_detail", args=[self.student.pk]),
            reverse("edit_admission", args=[self.student.pk]),
            reverse("collect_fee", args=[self.student.pk]),
            reverse("view_receipt", args=[receipt.pk]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_admission_flow_creates_student_and_redirects_to_fee(self):
        self.login()
        resp = self.client.post(reverse("create_admission"), dict(
            full_name="New Kid", guardian_name="P", phone="9123456780", school_or_college="S",
            grade_or_year="8", address="a", course=self.course.pk, batch_timing="4pm",
            discount_amount="0", admission_date="2026-01-01",
        ))
        s = StudentAdmission.objects.get(full_name="New Kid")
        self.assertRedirects(resp, reverse("collect_fee", args=[s.pk]))

    def test_collect_fee_creates_receipt_and_blocks_overpay(self):
        self.login()
        url = reverse("collect_fee", args=[self.student.pk])
        bad = self.client.post(url, {"amount_paid": "99999", "payment_mode": "CASH"})
        self.assertEqual(bad.status_code, 200)
        self.assertEqual(FeeReceipt.objects.count(), 0)
        good = self.client.post(url, {"amount_paid": "4000", "payment_mode": "CASH"})
        r = FeeReceipt.objects.get()
        self.assertRedirects(good, reverse("view_receipt", args=[r.pk]))

    def test_collect_fee_redirects_when_fully_paid(self):
        self.login()
        FeeReceipt.objects.create(student=self.student, amount_paid=10000, payment_mode="CASH")
        resp = self.client.get(reverse("collect_fee", args=[self.student.pk]))
        self.assertRedirects(resp, reverse("student_detail", args=[self.student.pk]))

    def test_verify_receipt_is_public_and_404s_on_unknown(self):
        r = FeeReceipt.objects.create(student=self.student, amount_paid=100, payment_mode="CASH")
        resp = self.client.get(reverse("verify_receipt", args=[r.verification_uuid]))
        self.assertContains(resp, r.receipt_no)
        self.assertNotContains(resp, self.student.phone)  # no PII beyond what's needed
        self.assertEqual(self.client.get(reverse("verify_receipt", args=[uuid.uuid4()])).status_code, 404)

    def test_kit_toggle_requires_post(self):
        self.login()
        url = reverse("toggle_kit_status", args=[self.student.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.kit_issued)

    def test_directory_filters_and_htmx_partial(self):
        self.login()
        make_student(self.course, full_name="Zed Other", phone="9000000001")
        resp = self.client.get(reverse("student_directory"), {"q": "Zed"}, headers={"HX-Request": "true"})
        self.assertContains(resp, "Zed Other")
        self.assertNotContains(resp, "Aarav")
        self.assertNotContains(resp, "<html")  # partial only
        due = self.client.get(reverse("student_directory"), {"fee": "paid"})
        self.assertNotContains(due, "Aarav Sharma")

    def test_csv_export_neutralises_formulas(self):
        self.login()
        make_student(self.course, full_name="=HYPERLINK(\"http://x\")", phone="9000000002")
        resp = self.client.get(reverse("export_students"))
        rows = list(csv.reader(io.StringIO(resp.content.decode())))
        names = [r[1] for r in rows[1:]]
        self.assertIn("'=HYPERLINK(\"http://x\")", names)

    def test_logout_requires_post_and_works(self):
        self.login()
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_unknown_url_uses_custom_404(self):
        self.assertEqual(self.client.get("/nope/").status_code, 404)
