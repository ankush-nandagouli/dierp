import os
import re
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from institute.models import Attendance, Batch, CourseTrack, FeeReceipt, SiteSettings, StudentAdmission, Trainer

User = get_user_model()
PW = "Str0ng-Pass-phrase-42"
MEDIA = tempfile.mkdtemp(prefix="erp-test-media-")


def png_bytes(size=(40, 40), color=(30, 60, 200)):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def png_upload(name="p.png", **kw):
    return SimpleUploadedFile(name, png_bytes(**kw), content_type="image/png")


def make_course(code="WEB", fee="9000", published=True, title=None, **kw):
    return CourseTrack.objects.create(
        code=code, title=title or f"Course {code}", duration="3M", total_fee=Decimal(fee),
        is_published=published, summary=f"Summary for {code}", **kw,
    )


def make_trainer(username="trainer1", first="Tina"):
    user = User.objects.create_user(username, f"{username}@example.com", PW, first_name=first)
    return Trainer.objects.create(user=user, phone="9811111111")


def make_batch(course, trainer=None, name="Morning", **kw):
    return Batch.objects.create(course=course, trainer=trainer, name=name, start_date=kw.pop("start_date", timezone.localdate() - timedelta(days=30)), **kw)


def make_student(course, email="stu@example.com", *, verified=True, status="ACTIVE", batch=None, with_user=True, name="Aarav Sharma", **kw):
    user = User.objects.create_user(email, email, PW, first_name=name.split()[0]) if with_user else None
    return StudentAdmission.objects.create(
        user=user, email=email, email_verified=verified, status=status, batch=batch, full_name=name,
        guardian_name="R Sharma", phone="9876543210", school_or_college="KV", grade_or_year="10",
        course=course, **kw,
    )


@override_settings(MEDIA_ROOT=MEDIA, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PortalTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()  # rate-limit counters must not leak between tests
        mail.outbox.clear()


# ============================================================ public site & SEO
class PublicSiteTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.course = make_course(title="Full Stack Web", description="Para one.\n\nPara two.")
        self.hidden = make_course("APP", published=False, title="Secret Course")

    def test_home_has_seo_essentials(self):
        r = self.client.get(reverse("portal:home"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("<title>", html)
        self.assertRegex(html, r'<meta name="description" content="[^"]{20,}')
        self.assertIn('rel="canonical"', html)
        self.assertIn('property="og:title"', html)
        self.assertIn('"@type": "EducationalOrganization"', html)
        self.assertIn('name="robots" content="index, follow', html)
        self.assertContains(r, "Full Stack Web")
        self.assertNotContains(r, "Secret Course")
        self.assertEqual(html.count("<h1"), 1)

    def test_course_detail_seo_and_jsonld(self):
        r = self.client.get(self.course.get_absolute_url())
        self.assertContains(r, "<title>Full Stack Web Course in Waraseoni | Dakshyam Innovations</title>", html=False)
        self.assertContains(r, '"@type": "Course"')
        self.assertContains(r, '"@type": "BreadcrumbList"')
        self.assertContains(r, "Para one.")
        self.assertContains(r, f"http://testserver{self.course.get_absolute_url()}")  # absolute canonical

    def test_unpublished_course_is_404_and_not_registrable(self):
        self.assertEqual(self.client.get(self.hidden.get_absolute_url()).status_code, 404)
        r = self.client.get(reverse("portal:register") + f"?course={self.hidden.slug}")
        self.assertNotContains(r, "Secret Course")

    def test_fees_hidden_unless_enabled_and_jsonld_offer(self):
        self.assertNotContains(self.client.get(self.course.get_absolute_url()), "9000")
        s = SiteSettings.load(); s.show_fees = True; s.save()
        r = self.client.get(self.course.get_absolute_url())
        self.assertContains(r, "9000")
        self.assertContains(r, '"priceCurrency": "INR"')

    def test_sitemap_lists_published_only(self):
        r = self.client.get("/sitemap.xml")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn(self.course.get_absolute_url(), body)
        self.assertNotIn(self.hidden.slug, body)
        self.assertIn("/courses/</loc>", body)

    def test_robots_txt(self):
        r = self.client.get("/robots.txt")
        self.assertEqual(r["Content-Type"].split(";")[0], "text/plain")
        body = r.content.decode()
        self.assertIn("Sitemap: http://testserver/sitemap.xml", body)
        for path in ("/admin/", "/student/", "/trainer/", "/dashboard/", "/accounts/"):
            self.assertIn(f"Disallow: {path}", body)

    def test_private_and_auth_pages_are_noindex(self):
        for url in (reverse("login"), reverse("portal:register_done"), reverse("portal:resend_verification")):
            self.assertContains(self.client.get(url), 'content="noindex, nofollow"')

    def test_slug_generated_and_unique(self):
        a = make_course("CORE", title="Same Title")
        b = make_course("VOC", title="Same Title")
        self.assertEqual(a.slug, "same-title")
        self.assertEqual(b.slug, "same-title-2")

    def test_contact_page_and_custom_404(self):
        self.assertEqual(self.client.get(reverse("portal:contact")).status_code, 200)
        self.assertEqual(self.client.get("/does-not-exist/").status_code, 404)

    def test_logo_appears_on_public_site_when_uploaded(self):
        s = SiteSettings.load(); s.logo = png_upload("logo.png"); s.save()
        r = self.client.get(reverse("portal:home"))
        self.assertContains(r, s.logo.url)
        self.assertContains(r, 'property="og:image"')


# ======================================================= registration validation
class RegistrationTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.course = make_course()
        self.url = reverse("portal:register")

    def payload(self, **over):
        data = dict(
            full_name="Riya Verma", date_of_birth="2010-05-20", guardian_name="Mohan Verma", phone="9123456789",
            whatsapp_no="", email="Riya@Example.com", school_or_college="Govt School", grade_or_year="Class 9",
            address="Ward 3, Waraseoni", course=self.course.pk, batch="", password1=PW, password2=PW,
            accept_terms="on", website="",
        )
        data.update(over)
        return data

    def test_successful_registration_creates_pending_unverified_student_and_sends_email(self):
        r = self.client.post(self.url, self.payload())
        self.assertRedirects(r, reverse("portal:register_done"))
        user = User.objects.get(username="riya@example.com")
        self.assertEqual(user.email, "riya@example.com")
        self.assertFalse(user.is_staff)
        s = user.student_profile
        self.assertEqual((s.status, s.email_verified, s.registered_online), ("PENDING", False, True))
        self.assertEqual(s.whatsapp_no, "9123456789")  # defaults to phone
        self.assertEqual(s.course, self.course)
        self.assertRegex(s.enrollment_no, r"^DI-\d{4}-\d{4}$")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["riya@example.com"])
        self.assertRegex(mail.outbox[0].body, r"/verify-email/\S+")

    def test_registration_with_photo(self):
        r = self.client.post(self.url, {**self.payload(), "photo": png_upload()})
        self.assertEqual(r.status_code, 302)
        photo = StudentAdmission.objects.get().photo
        self.assertTrue(photo.name.startswith("students/photos/"))
        self.assertNotIn("riya", photo.name.lower())  # random, unguessable file name

    def test_rejects_bad_input(self):
        today = date.today()
        cases = {
            "phone": ["12345", "5123456789", "98765abcde"],
            "date_of_birth": [str(today + timedelta(days=5)), str(today - timedelta(days=365)), "1900-01-01"],
            "full_name": ["R", "Riya123", "<script>"],
            "email": ["not-an-email"],
            "password2": ["different-password-1"],
            "password1": ["short", "12345678"],
        }
        for field, values in cases.items():
            for v in values:
                data = self.payload(**{field: v})
                if field == "password1":
                    data["password2"] = v
                r = self.client.post(self.url, data)
                self.assertEqual(r.status_code, 200, (field, v))
                self.assertIn(field, r.context["form"].errors, (field, v))
        self.assertEqual(User.objects.count(), 0)

    def test_terms_required(self):
        data = self.payload(); data.pop("accept_terms")
        self.assertIn("accept_terms", self.client.post(self.url, data).context["form"].errors)

    def test_duplicate_email_rejected_case_insensitively(self):
        User.objects.create_user("riya@example.com", "riya@example.com", PW)
        r = self.client.post(self.url, self.payload(email="RIYA@example.COM"))
        self.assertIn("email", r.context["form"].errors)

    def test_email_of_existing_office_admission_is_rejected(self):
        make_student(self.course, "riya@example.com", with_user=False)
        r = self.client.post(self.url, self.payload())
        self.assertIn("email", r.context["form"].errors)
        self.assertEqual(StudentAdmission.objects.count(), 1)

    def test_honeypot_blocks_bots(self):
        r = self.client.post(self.url, self.payload(website="http://spam.example"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_unpublished_course_cannot_be_chosen(self):
        hidden = make_course("APP", published=False)
        r = self.client.post(self.url, self.payload(course=hidden.pk))
        self.assertIn("course", r.context["form"].errors)

    def test_batch_must_belong_to_course(self):
        other = make_batch(make_course("IOT"), name="Other")
        r = self.client.post(self.url, self.payload(batch=other.pk))
        self.assertIn("batch", r.context["form"].errors)
        ok = make_batch(self.course)
        self.assertEqual(self.client.post(self.url, self.payload(batch=ok.pk)).status_code, 302)
        self.assertEqual(StudentAdmission.objects.get().batch, ok)

    def test_oversized_and_fake_images_rejected(self):
        big = SimpleUploadedFile("big.png", png_bytes((1400, 1400)) + os.urandom(2_200_000), content_type="image/png")
        self.assertIn("photo", self.client.post(self.url, {**self.payload(), "photo": big}).context["form"].errors)
        fake = SimpleUploadedFile("x.png", b"not really an image", content_type="image/png")
        self.assertIn("photo", self.client.post(self.url, {**self.payload(), "photo": fake}).context["form"].errors)
        self.assertEqual(User.objects.count(), 0)

    def test_registration_rate_limit(self):
        for i in range(5):
            r = self.client.post(self.url, self.payload(email=f"u{i}@example.com"))
            self.assertEqual(r.status_code, 302, i)
        r = self.client.post(self.url, self.payload(email="u6@example.com"))
        self.assertEqual(r.status_code, 429)
        self.assertFalse(User.objects.filter(username="u6@example.com").exists())

    def test_logged_in_users_are_sent_away_from_register(self):
        make_student(self.course)
        self.client.login(username="stu@example.com", password=PW)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_course_prefilled_from_query(self):
        r = self.client.get(self.url + f"?course={self.course.slug}")
        self.assertEqual(r.context["form"].initial["course"], self.course)


# ================================================== email verification & sign-in
class VerificationAndLoginTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.course = make_course()
        self.student = make_student(self.course, verified=False, status="PENDING")

    def token_link(self):
        from portal.emails import send_verification_email
        from django.test import RequestFactory
        req = RequestFactory().get("/", HTTP_HOST="testserver")
        send_verification_email(req, self.student.user, SiteSettings.load())
        return re.search(r"http://testserver(/verify-email/\S+)", mail.outbox[-1].body).group(1)

    def login(self, ident="stu@example.com", pw=PW):
        return self.client.post(reverse("login"), {"username": ident, "password": pw})

    def test_cannot_sign_in_until_email_verified(self):
        r = self.login()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["form"].unverified)
        self.assertContains(r, "confirm your email")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verification_link_activates_and_allows_login(self):
        r = self.client.get(self.token_link())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Email confirmed")
        self.student.refresh_from_db()
        self.assertTrue(self.student.email_verified)
        r = self.login()
        self.assertRedirects(r, reverse("portal:after_login"), fetch_redirect_response=False)

    def test_tampered_token_rejected(self):
        link = self.token_link()
        r = self.client.get(link.rstrip("/")[:-3] + "xyz/")
        self.assertEqual(r.status_code, 400)
        self.student.refresh_from_db()
        self.assertFalse(self.student.email_verified)

    def test_expired_token_rejected(self):
        link = self.token_link()
        with override_settings(EMAIL_VERIFICATION_MAX_AGE=-1):
            self.assertEqual(self.client.get(link).status_code, 400)

    def test_token_invalid_if_email_changed_after_issue(self):
        link = self.token_link()
        self.student.user.email = "changed@example.com"; self.student.user.save()
        self.assertEqual(self.client.get(link).status_code, 400)

    def test_resend_is_neutral_and_only_mails_unverified_accounts(self):
        url = reverse("portal:resend_verification")
        r1 = self.client.post(url, {"email": "nobody@example.com"})
        self.assertContains(r1, "on its way")
        self.assertEqual(len(mail.outbox), 0)
        r2 = self.client.post(url, {"email": "STU@example.com"})
        self.assertContains(r2, "on its way")
        self.assertEqual(len(mail.outbox), 1)
        self.student.email_verified = True; self.student.save()
        self.client.post(url, {"email": "stu@example.com"})
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_rate_limited_per_address(self):
        url = reverse("portal:resend_verification")
        for _ in range(6):
            self.client.post(url, {"email": "stu@example.com"})
        self.assertEqual(len(mail.outbox), 3)

    def test_login_by_email_case_insensitive_and_by_username(self):
        self.student.email_verified = True; self.student.save()
        self.assertEqual(self.login("STU@Example.com").status_code, 302)
        self.client.logout()
        t = make_trainer("coach")
        self.assertEqual(self.login("coach").status_code, 302)
        self.client.logout()
        self.assertEqual(self.login("coach@example.com").status_code, 302)

    def test_wrong_password_and_throttle(self):
        self.student.email_verified = True; self.student.save()
        for _ in range(10):
            self.assertEqual(self.login(pw="bad").status_code, 200)
        r = self.login()  # even the right password is refused while throttled
        self.assertContains(r, "Too many failed attempts")
        cache.clear()
        self.assertEqual(self.login().status_code, 302)

    def test_inactive_user_cannot_sign_in(self):
        self.student.email_verified = True; self.student.save()
        self.student.user.is_active = False; self.student.user.save()
        self.assertEqual(self.login().status_code, 200)

    def test_role_based_redirect_after_login(self):
        self.student.email_verified = True; self.student.save()
        self.client.login(username="stu@example.com", password=PW)
        self.assertRedirects(self.client.get(reverse("portal:after_login")), reverse("portal:student_dashboard"))
        self.client.logout()
        make_trainer("coach")
        self.client.login(username="coach", password=PW)
        self.assertRedirects(self.client.get(reverse("portal:after_login")), reverse("portal:trainer_dashboard"))
        self.client.logout()
        User.objects.create_user("boss", "boss@example.com", PW, is_staff=True)
        self.client.login(username="boss", password=PW)
        self.assertRedirects(self.client.get(reverse("portal:after_login")), reverse("dashboard"))

    def test_password_reset_flow_sends_branded_email(self):
        self.student.email_verified = True; self.student.save()
        self.client.post(reverse("password_reset"), {"email": "stu@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Dakshyam Innovations", mail.outbox[0].subject)
        self.assertRegex(mail.outbox[0].body, r"/accounts/password/reset/[\w-]+/[\w-]+/")


# ====================================================== role isolation (security)
class RoleAccessTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.course = make_course()
        self.trainer = make_trainer()
        self.batch = make_batch(self.course, self.trainer)
        self.student = make_student(self.course, batch=self.batch)
        self.staff = User.objects.create_user("boss", "boss@example.com", PW, is_staff=True)
        self.receipt = FeeReceipt.objects.create(student=self.student, amount_paid=100, payment_mode="CASH")

    STAFF_URLS = ["dashboard", "create_admission", "student_directory", "export_students", "kit_tracker", "receipt_list"]

    def test_students_and_trainers_cannot_open_staff_pages(self):
        for who, pw in (("stu@example.com", PW), ("trainer1", PW)):
            self.client.login(username=who, password=pw)
            for name in self.STAFF_URLS:
                self.assertEqual(self.client.get(reverse(name)).status_code, 403, (who, name))
            for url in (reverse("student_detail", args=[self.student.pk]), reverse("view_receipt", args=[self.receipt.pk]),
                        reverse("collect_fee", args=[self.student.pk]), reverse("staff_id_card", args=[self.student.pk]),
                        reverse("branding_settings")):
                self.assertEqual(self.client.get(url).status_code, 403, (who, url))
            for url in (reverse("approve_admission", args=[self.student.pk]), reverse("invite_student", args=[self.student.pk])):
                self.assertEqual(self.client.post(url).status_code, 403, (who, url))
            self.client.logout()

    def test_students_cannot_use_trainer_pages_and_vice_versa(self):
        self.client.login(username="stu@example.com", password=PW)
        for url in (reverse("portal:trainer_dashboard"), reverse("portal:trainer_attendance", args=[self.batch.pk])):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.client.login(username="trainer1", password=PW)
        for url in (reverse("portal:student_dashboard"), reverse("portal:student_receipts"), reverse("portal:student_id_card")):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_staff_without_profiles_cannot_open_portals(self):
        self.client.login(username="boss", password=PW)
        self.assertEqual(self.client.get(reverse("portal:student_dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:trainer_dashboard")).status_code, 403)

    def test_anonymous_redirected_to_login(self):
        for url in (reverse("portal:student_dashboard"), reverse("portal:trainer_dashboard"),
                    reverse("portal:student_profile"), reverse("portal:trainer_attendance", args=[self.batch.pk])):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302)
            self.assertIn("/accounts/login/", r["Location"])

    def test_unverified_student_gets_no_portal_access_even_with_a_session(self):
        self.student.email_verified = False; self.student.save()
        self.client.force_login(self.student.user)
        self.assertEqual(self.client.get(reverse("portal:student_dashboard")).status_code, 403)

    def test_student_or_trainer_cannot_enter_django_admin(self):
        self.client.login(username="stu@example.com", password=PW)
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])


# ============================================================== student portal
class StudentPortalTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.course = make_course(fee="10000")
        self.trainer = make_trainer(first="Tina")
        self.batch = make_batch(self.course, self.trainer, name="Evening A", timing="06:00 PM - 07:30 PM")
        self.student = make_student(self.course, batch=self.batch, discount_amount=Decimal("1000"))
        self.client.login(username="stu@example.com", password=PW)

    def test_dashboard_shows_course_batch_trainer_fees_attendance(self):
        FeeReceipt.objects.create(student=self.student, amount_paid=Decimal("2500"), payment_mode="CASH")
        today = timezone.localdate()
        for i, st in enumerate("PPLA"):
            Attendance.objects.create(student=self.student, batch=self.batch, date=today - timedelta(days=i), status=st)
        r = self.client.get(reverse("portal:student_dashboard"))
        self.assertContains(r, "Course WEB")
        self.assertContains(r, "Evening A")
        self.assertContains(r, "06:00 PM - 07:30 PM")
        self.assertContains(r, "Tina")
        self.assertContains(r, "9000")   # net payable after discount
        self.assertContains(r, "6500")   # balance
        self.assertContains(r, "75%")    # (2 present + 1 late) / 4
        self.assertEqual(r["Cache-Control"] if "Cache-Control" in r else "", r.get("Cache-Control", ""))

    def test_pending_student_sees_notice(self):
        self.student.status = "PENDING"; self.student.save()
        self.assertContains(self.client.get(reverse("portal:student_dashboard")), "Awaiting approval")

    def test_receipts_list_and_own_receipt_view(self):
        rc = FeeReceipt.objects.create(student=self.student, amount_paid=500, payment_mode="UPI", transaction_ref="UTR9")
        r = self.client.get(reverse("portal:student_receipts"))
        self.assertContains(r, rc.receipt_no)
        d = self.client.get(reverse("portal:student_receipt", args=[rc.pk]))
        self.assertContains(d, rc.receipt_no)
        self.assertContains(d, "data:image/png;base64,")

    def test_cannot_view_another_students_receipt(self):
        other = make_student(self.course, "other@example.com", name="Other Kid")
        rc = FeeReceipt.objects.create(student=other, amount_paid=500, payment_mode="CASH")
        self.assertEqual(self.client.get(reverse("portal:student_receipt", args=[rc.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("portal:student_receipts")), rc.receipt_no)

    def test_profile_edit_updates_allowed_fields_only(self):
        url = reverse("portal:student_profile")
        r = self.client.post(url, {
            "guardian_name": "New Guardian", "phone": "9000000009", "whatsapp_no": "", "date_of_birth": "2009-01-02",
            "school_or_college": "New School", "grade_or_year": "11", "address": "New Address",
            # attempts to tamper with fields students must not control:
            "full_name": "Hacked Name", "course": make_course("IOT").pk, "status": "COMPLETED",
            "discount_amount": "99999", "enrollment_no": "HACK-1", "email": "evil@example.com",
        })
        self.assertRedirects(r, url)
        s = StudentAdmission.objects.get(pk=self.student.pk)
        self.assertEqual((s.guardian_name, s.phone, s.address, s.school_or_college), ("New Guardian", "9000000009", "New Address", "New School"))
        self.assertEqual(s.whatsapp_no, "9000000009")
        self.assertEqual((s.full_name, s.course_id, s.status, s.discount_amount, s.email), ("Aarav Sharma", self.course.pk, "ACTIVE", Decimal("1000"), "stu@example.com"))
        self.assertNotEqual(s.enrollment_no, "HACK-1")

    def test_profile_validation_errors(self):
        url = reverse("portal:student_profile")
        base = {"guardian_name": "G", "phone": "9000000009", "school_or_college": "S", "grade_or_year": "9", "address": "A", "date_of_birth": ""}
        for override, field in (({"phone": "123"}, "phone"), ({"guardian_name": "G1!"}, "guardian_name"), ({"date_of_birth": "2999-01-01"}, "date_of_birth")):
            r = self.client.post(url, {**base, **override})
            self.assertEqual(r.status_code, 200)
            self.assertIn(field, r.context["form"].errors)

    def test_profile_photo_upload(self):
        base = {"guardian_name": "G G", "phone": "9000000009", "school_or_college": "S", "grade_or_year": "9", "address": "A"}
        self.client.post(reverse("portal:student_profile"), {**base, "photo": png_upload()})
        self.student.refresh_from_db()
        self.assertTrue(self.student.photo.name.startswith("students/photos/"))

    def test_id_card_for_active_student(self):
        r = self.client.get(reverse("portal:student_id_card"))
        self.assertEqual(r.status_code, 200)
        for text in (self.student.enrollment_no, "Aarav Sharma", "Course WEB", "Evening A", "STUDENT IDENTITY CARD", "Valid till"):
            self.assertContains(r, text)
        self.assertContains(r, 'src="data:image/png;base64,')
        self.assertContains(r, 'content="noindex, nofollow"')
        self.assertNotContains(r, "9876543210")  # no phone number printed on the card

    def test_id_card_not_available_until_approved(self):
        self.student.status = "PENDING"; self.student.save()
        r = self.client.get(reverse("portal:student_id_card"))
        self.assertContains(r, "not available yet")
        self.assertNotContains(r, "STUDENT IDENTITY CARD")

    def test_id_card_qr_verification_page(self):
        from portal.idcard import id_card_context
        from django.test import RequestFactory
        ctx = id_card_context(RequestFactory().get("/", HTTP_HOST="testserver"), self.student)
        path = ctx["verify_url"].replace("http://testserver", "")
        self.client.logout()  # public page
        r = self.client.get(path)
        self.assertContains(r, "Valid student ID")
        self.assertContains(r, self.student.enrollment_no)
        self.assertNotContains(r, "9876543210")
        self.assertEqual(self.client.get(path.rstrip("/")[:-4] + "abcd/").status_code, 404)

    def test_expired_id_shows_not_valid(self):
        from portal.emails import make_id_token
        StudentAdmission.objects.filter(pk=self.student.pk).update(admission_date=date(2020, 1, 1))
        r = self.client.get(reverse("portal:verify_id", args=[make_id_token(self.student)]))
        self.assertContains(r, "Not currently valid")

    def test_dropped_student_id_is_not_valid(self):
        from portal.emails import make_id_token
        StudentAdmission.objects.filter(pk=self.student.pk).update(status="DROPPED")
        self.assertContains(self.client.get(reverse("portal:verify_id", args=[make_id_token(self.student)])), "Not currently valid")

    def test_change_password(self):
        r = self.client.post(reverse("password_change"), {"old_password": PW, "new_password1": "An0ther-Strong-pass-77", "new_password2": "An0ther-Strong-pass-77"})
        self.assertRedirects(r, reverse("password_change_done"))
        self.client.logout()
        self.assertTrue(self.client.login(username="stu@example.com", password="An0ther-Strong-pass-77"))


# ============================================================== trainer & attendance
class TrainerAttendanceTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.course = make_course()
        self.trainer = make_trainer("trainer1", "Tina")
        self.other_trainer = make_trainer("trainer2", "Omar")
        self.batch = make_batch(self.course, self.trainer)
        self.other_batch = make_batch(self.course, self.other_trainer, name="Other")
        self.s1 = make_student(self.course, "s1@example.com", batch=self.batch, name="Anil Kumar")
        self.s2 = make_student(self.course, "s2@example.com", batch=self.batch, name="Bela Singh")
        self.pending = make_student(self.course, "s3@example.com", batch=self.batch, name="Pending Kid", status="PENDING")
        self.outsider = make_student(self.course, "s4@example.com", batch=self.other_batch, name="Outsider")
        self.client.login(username="trainer1", password=PW)
        self.url = reverse("portal:trainer_attendance", args=[self.batch.pk])
        self.today = timezone.localdate()

    def post(self, statuses, day=None, **extra):
        data = {"date": (day or self.today).isoformat()}
        data.update({f"status_{s.pk}": st for s, st in statuses.items()})
        data.update(extra)
        return self.client.post(self.url, data)

    def test_dashboard_lists_only_own_batches(self):
        r = self.client.get(reverse("portal:trainer_dashboard"))
        self.assertContains(r, "Morning")
        self.assertNotContains(r, "Other")
        self.assertContains(r, "Today pending")

    def test_mark_attendance_for_active_students_only(self):
        r = self.get_form = self.client.get(self.url)
        self.assertContains(r, "Anil Kumar"); self.assertContains(r, "Bela Singh")
        self.assertNotContains(r, "Pending Kid"); self.assertNotContains(r, "Outsider")
        r = self.post({self.s1: "P", self.s2: "A"}, remarks_1="x")
        self.assertEqual(r.status_code, 302)
        recs = {a.student_id: a for a in Attendance.objects.filter(batch=self.batch, date=self.today)}
        self.assertEqual({k: v.status for k, v in recs.items()}, {self.s1.pk: "P", self.s2.pk: "A"})
        self.assertEqual(recs[self.s1.pk].marked_by, self.trainer.user)
        self.assertContains(self.client.get(reverse("portal:trainer_dashboard")), "Today marked")

    def test_resubmitting_updates_instead_of_duplicating(self):
        self.post({self.s1: "P", self.s2: "P"})
        self.post({self.s1: "L", self.s2: "A"}, **{f"remarks_{self.s2.pk}": "sick"})
        self.assertEqual(Attendance.objects.count(), 2)
        a = Attendance.objects.get(student=self.s2)
        self.assertEqual((a.status, a.remarks), ("A", "sick"))
        self.assertEqual(Attendance.objects.get(student=self.s1).status, "L")

    def test_missing_or_invalid_status_saves_nothing(self):
        r = self.post({self.s1: "P"})  # s2 missing
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Select a status for Bela Singh")
        self.assertEqual(Attendance.objects.count(), 0)
        r = self.post({self.s1: "P", self.s2: "Z"})
        self.assertContains(r, "Select a status for Bela Singh")
        self.assertEqual(Attendance.objects.count(), 0)

    def test_cannot_touch_another_trainers_batch(self):
        other_url = reverse("portal:trainer_attendance", args=[self.other_batch.pk])
        self.assertEqual(self.client.get(other_url).status_code, 404)
        self.assertEqual(self.client.post(other_url, {"date": self.today.isoformat(), f"status_{self.outsider.pk}": "P"}).status_code, 404)
        for name in ("trainer_batch", "trainer_report"):
            self.assertEqual(self.client.get(reverse(f"portal:{name}", args=[self.other_batch.pk])).status_code, 404)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_injected_student_ids_are_ignored(self):
        self.post({self.s1: "P", self.s2: "P", self.outsider: "P", self.pending: "P"})
        self.assertEqual(set(Attendance.objects.values_list("student_id", flat=True)), {self.s1.pk, self.s2.pk})

    def test_future_date_rejected(self):
        r = self.post({self.s1: "P", self.s2: "P"}, day=self.today + timedelta(days=1))
        self.assertContains(r, "future date")
        self.assertEqual(Attendance.objects.count(), 0)

    def test_edit_window_enforced_and_configurable(self):
        old = self.today - timedelta(days=10)
        r = self.post({self.s1: "P", self.s2: "P"}, day=old)
        self.assertContains(r, "within the last 7 days")
        self.assertEqual(Attendance.objects.count(), 0)
        s = SiteSettings.load(); s.trainer_edit_window_days = 14; s.save()
        self.assertEqual(self.post({self.s1: "P", self.s2: "P"}, day=old).status_code, 302)
        self.assertEqual(Attendance.objects.count(), 2)

    def test_date_before_batch_start_rejected(self):
        Batch.objects.filter(pk=self.batch.pk).update(start_date=self.today)
        r = self.post({self.s1: "P", self.s2: "P"}, day=self.today - timedelta(days=1))
        self.assertContains(r, "started on")
        self.assertEqual(Attendance.objects.count(), 0)

    def test_garbage_date_falls_back_to_today(self):
        r = self.client.get(self.url + "?date=not-a-date")
        self.assertEqual(r.context["day"], self.today)

    def test_model_validation_and_uniqueness(self):
        with self.assertRaises(ValidationError):
            Attendance(student=self.outsider, batch=self.batch, date=self.today, status="P").full_clean()
        with self.assertRaises(ValidationError):
            Attendance(student=self.s1, batch=self.batch, date=self.today + timedelta(days=2), status="P").full_clean()
        Attendance.objects.create(student=self.s1, batch=self.batch, date=self.today, status="P")
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            Attendance.objects.create(student=self.s1, batch=self.batch, date=self.today, status="A")

    def test_report_and_csv(self):
        d = [self.today - timedelta(days=i) for i in range(3)]
        for day, (a, b) in zip(d, [("P", "A"), ("L", "A"), ("P", "A")]):
            Attendance.objects.create(student=self.s1, batch=self.batch, date=day, status=a)
            Attendance.objects.create(student=self.s2, batch=self.batch, date=day, status=b)
        q = f"?from={d[-1].isoformat()}&to={self.today.isoformat()}"
        r = self.client.get(reverse("portal:trainer_report", args=[self.batch.pk]) + q)
        rows = {x["student"].pk: x for x in r.context["rows"]}
        self.assertEqual((rows[self.s1.pk]["present"], rows[self.s1.pk]["late"], rows[self.s1.pk]["percent"]), (2, 1, 100))
        self.assertEqual((rows[self.s2.pk]["absent"], rows[self.s2.pk]["percent"]), (3, 0))
        csv_r = self.client.get(reverse("portal:trainer_report", args=[self.batch.pk]) + q + "&format=csv")
        self.assertEqual(csv_r["Content-Type"], "text/csv")
        self.assertIn("Anil Kumar,2,1,0,3,100", csv_r.content.decode())

    def test_batch_page_lists_students(self):
        r = self.client.get(reverse("portal:trainer_batch", args=[self.batch.pk]))
        self.assertContains(r, "Anil Kumar"); self.assertNotContains(r, "Pending Kid")

    def test_trainer_profile_edit(self):
        r = self.client.post(reverse("portal:trainer_profile"), {
            "first_name": "Tina", "last_name": "Rao", "phone": "9822222222", "qualification": "M.Tech", "bio": "Hello",
            "photo": png_upload(),
        })
        self.assertRedirects(r, reverse("portal:trainer_profile"))
        self.trainer.refresh_from_db(); self.trainer.user.refresh_from_db()
        self.assertEqual((self.trainer.user.last_name, self.trainer.phone, self.trainer.qualification), ("Rao", "9822222222", "M.Tech"))
        self.assertTrue(self.trainer.photo.name.startswith("trainers/photos/"))
        bad = self.client.post(reverse("portal:trainer_profile"), {"first_name": "T", "phone": "1", "qualification": "", "bio": ""})
        self.assertEqual(bad.status_code, 200)
        self.assertIn("phone", bad.context["form"].errors)

    def test_student_dashboard_reflects_marked_attendance(self):
        self.post({self.s1: "P", self.s2: "A"})
        self.client.logout(); self.client.login(username="s1@example.com", password=PW)
        self.assertContains(self.client.get(reverse("portal:student_dashboard")), "100%")


# ===================================================== staff-side features & admin
class StaffFeatureTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.course = make_course()
        self.staff = User.objects.create_user("boss", "boss@example.com", PW, is_staff=True)
        self.root = User.objects.create_superuser("root", "root@example.com", PW)

    def test_dashboard_shows_pending_applications_and_excludes_their_dues(self):
        pend = make_student(self.course, "p@example.com", status="PENDING", verified=False, name="Pend Ing")
        active = make_student(self.course, "a@example.com", name="Act Ive")
        self.client.login(username="boss", password=PW)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "1 online application")
        self.assertContains(r, "Pend Ing")
        self.assertEqual(r.context["total_pending"], active.balance_due)

    def test_approve_admission(self):
        s = make_student(self.course, "p@example.com", status="PENDING")
        self.client.login(username="boss", password=PW)
        url = reverse("approve_admission", args=[s.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse("student_detail", args=[s.pk]))
        s.refresh_from_db(); self.assertEqual(s.status, "ACTIVE")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(s.enrollment_no, mail.outbox[0].body)
        self.client.post(url)  # idempotent: no second email
        self.assertEqual(len(mail.outbox), 1)

    def test_approve_does_not_email_unverified_applicant(self):
        s = make_student(self.course, "p@example.com", status="PENDING", verified=False)
        self.client.login(username="boss", password=PW)
        self.client.post(reverse("approve_admission", args=[s.pk]))
        self.assertEqual(len(mail.outbox), 0)

    def test_invite_creates_login_and_emails_set_password_link(self):
        s = make_student(self.course, "kid@example.com", with_user=False, verified=False)
        self.client.login(username="boss", password=PW)
        url = reverse("invite_student", args=[s.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        s.refresh_from_db()
        self.assertIsNotNone(s.user); self.assertTrue(s.email_verified); self.assertFalse(s.user.is_staff)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["kid@example.com"])
        self.assertRegex(mail.outbox[0].body, r"/accounts/password/reset/[\w-]+/[\w-]+/")
        self.assertFalse(s.user.has_usable_password() is False)  # random password set, nobody knows it
        self.client.post(url)  # second invite is a no-op
        self.assertEqual(len(mail.outbox), 1)

    def test_invite_requires_email_and_unique_address(self):
        no_email = make_student(self.course, "x@example.com", with_user=False); no_email.email = ""; no_email.save()
        User.objects.create_user("taken@example.com", "taken@example.com", PW)
        clash = make_student(self.course, "taken@example.com", with_user=False, name="Clash Kid")
        self.client.login(username="boss", password=PW)
        self.client.post(reverse("invite_student", args=[no_email.pk]))
        self.client.post(reverse("invite_student", args=[clash.pk]))
        no_email.refresh_from_db(); clash.refresh_from_db()
        self.assertIsNone(no_email.user); self.assertIsNone(clash.user)
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_can_open_any_students_id_card(self):
        s = make_student(self.course, "k@example.com", with_user=False)
        self.client.login(username="boss", password=PW)
        self.assertContains(self.client.get(reverse("staff_id_card", args=[s.pk])), s.enrollment_no)

    def test_staff_edit_assigns_batch_and_checks_course_match(self):
        s = make_student(self.course, "k@example.com", with_user=False)
        good = make_batch(self.course); bad = make_batch(make_course("IOT"), name="Wrong")
        self.client.login(username="boss", password=PW)
        url = reverse("edit_admission", args=[s.pk])
        form = dict(full_name=s.full_name, guardian_name="G G", phone="9876543210", whatsapp_no="9876543210", email=s.email,
                    school_or_college="S", grade_or_year="9", address="A", course=self.course.pk, status="ACTIVE",
                    batch_timing="4pm", discount_amount="0", admission_date="2026-01-01")
        r = self.client.post(url, {**form, "batch": bad.pk}); self.assertEqual(r.status_code, 200)
        self.assertIn("batch", r.context["form"].errors)
        self.assertEqual(self.client.post(url, {**form, "batch": good.pk}).status_code, 302)
        s.refresh_from_db(); self.assertEqual(s.batch, good)

    def test_branding_requires_superuser(self):
        self.client.login(username="boss", password=PW)
        self.assertEqual(self.client.get(reverse("branding_settings")).status_code, 403)

    def test_superuser_uploads_logo_and_it_shows_everywhere(self):
        self.client.login(username="root", password=PW)
        data = dict(name="Dakshyam Innovations", tagline="Learn", phone="9822222222", email="hi@example.com",
                    address="Somewhere", city="Waraseoni", meta_description="Short desc", trainer_edit_window_days=7,
                    logo=png_upload("logo.png"))
        r = self.client.post(reverse("branding_settings"), data)
        self.assertRedirects(r, reverse("branding_settings"))
        site = SiteSettings.load()
        self.assertTrue(site.logo.name.startswith("branding/"))
        self.assertContains(self.client.get(reverse("dashboard")), site.logo.url)      # staff sidebar
        self.assertContains(self.client.get(reverse("portal:home")), site.logo.url)    # public site
        s = make_student(self.course, "k@example.com", with_user=False)
        self.assertContains(self.client.get(reverse("staff_id_card", args=[s.pk])), site.logo.url)  # ID card
        self.assertContains(self.client.get(reverse("portal:home")), "+91 9822222222")

    def test_logo_validation(self):
        self.client.login(username="root", password=PW)
        base = dict(name="N", tagline="", phone="", email="", address="A", city="C", meta_description="", trainer_edit_window_days=7)
        r = self.client.post(reverse("branding_settings"), {**base, "logo": SimpleUploadedFile("l.txt", b"hello", content_type="text/plain")})
        self.assertIn("logo", r.context["form"].errors)
        big = SimpleUploadedFile("big.png", png_bytes((1400, 1400)) + os.urandom(2_200_000), content_type="image/png")
        self.assertIn("logo", self.client.post(reverse("branding_settings"), {**base, "logo": big}).context["form"].errors)
        self.assertIn("phone", self.client.post(reverse("branding_settings"), {**base, "phone": "12"}).context["form"].errors)
        self.assertFalse(SiteSettings.load().logo)

    def test_site_settings_is_a_singleton(self):
        SiteSettings.objects.all().delete()
        a = SiteSettings.load(); b = SiteSettings.objects.create(name="Second")
        self.assertEqual(SiteSettings.objects.count(), 1)
        b.delete()
        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertEqual(a.pk, 1)

    def test_admin_creates_trainer_with_login_account(self):
        self.client.login(username="root", password=PW)
        url = "/admin/institute/trainer/add/"
        data = dict(username="newcoach", first_name="Nina", last_name="Roy", email="nina@example.com", password="Sup3r-secret-pass-99",
                    phone="9833333333", qualification="B.Tech", bio="")
        r = self.client.post(url, data)
        self.assertEqual(r.status_code, 302)
        t = Trainer.objects.get(user__username="newcoach")
        self.assertFalse(t.user.is_staff); self.assertFalse(t.user.is_superuser)
        self.assertTrue(t.user.check_password("Sup3r-secret-pass-99"))
        # duplicate username/email and weak password are rejected
        for override in ({"username": "NEWCOACH"}, {"email": "NINA@example.com", "username": "other"}, {"password": "123", "username": "x2", "email": "x2@example.com"}):
            bad = self.client.post(url, {**data, **override})
            self.assertEqual(bad.status_code, 200, override)
        self.assertEqual(Trainer.objects.count(), 1)
        # the new trainer can sign in and lands on the trainer portal
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "nina@example.com", "password": "Sup3r-secret-pass-99"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get(reverse("portal:trainer_dashboard")).status_code, 200)

    def test_admin_course_form_exposes_seo_fields_and_batch_admin_works(self):
        self.client.login(username="root", password=PW)
        self.assertContains(self.client.get(f"/admin/institute/coursetrack/{self.course.pk}/change/"), "Public website / SEO")
        for model in ("batch", "attendance", "trainer", "sitesettings", "studentadmission"):
            self.assertEqual(self.client.get(f"/admin/institute/{model}/").status_code, 200, model)

    def test_student_model_helpers(self):
        s = make_student(self.course, "k@example.com", with_user=False, date_of_birth=date.today() - timedelta(days=365 * 12))
        self.assertTrue(s.is_minor)
        self.assertEqual(s.valid_till, s.admission_date + timedelta(days=self.course.duration_days + 30))
        s.batch = make_batch(make_course("IOT"), name="X")
        with self.assertRaises(ValidationError):
            s.full_clean()
        self.assertEqual(s.attendance_stats(), {"total": 0, "present": 0, "late": 0, "absent": 0, "percent": None})


# ================================================= setup / migration safety net
class MigrationGuardTests(PortalTestCase):
    def tearDown(self):
        from portal.middleware import MigrationCheckMiddleware
        MigrationCheckMiddleware._ok = True

    @override_settings(DEBUG=True)  # the test runner forces DEBUG=False; the commands only show in DEBUG
    def test_unmigrated_database_shows_setup_page_not_a_crash(self):
        from unittest import mock
        from portal.middleware import MigrationCheckMiddleware
        MigrationCheckMiddleware._ok = False
        with mock.patch("portal.middleware.pending_migrations", return_value=["institute.0003_portal_features"]):
            r = self.client.get("/")
        self.assertEqual(r.status_code, 503)
        self.assertContains(r, "python manage.py migrate", status_code=503)
        self.assertContains(r, "institute.0003_portal_features", status_code=503)
        self.assertEqual(r["Retry-After"], "60")
        self.assertFalse(MigrationCheckMiddleware._ok)

    def test_setup_page_hides_commands_when_not_in_debug(self):
        from unittest import mock
        from portal.middleware import MigrationCheckMiddleware
        MigrationCheckMiddleware._ok = False
        with mock.patch("portal.middleware.pending_migrations", return_value=["x.0001"]), override_settings(DEBUG=False):
            r = self.client.get("/")
        self.assertEqual(r.status_code, 503)
        self.assertNotContains(r, "manage.py", status_code=503)

    def test_normal_when_up_to_date_and_stops_checking(self):
        from unittest import mock
        from portal.middleware import MigrationCheckMiddleware
        MigrationCheckMiddleware._ok = False
        with mock.patch("portal.middleware.pending_migrations", return_value=[]) as p:
            self.assertEqual(self.client.get("/").status_code, 200)
            self.assertEqual(self.client.get("/courses/").status_code, 200)
        self.assertEqual(p.call_count, 1)  # checked once, then skipped
        self.assertTrue(MigrationCheckMiddleware._ok)

    def test_real_check_finds_nothing_pending_on_a_migrated_database(self):
        from portal.middleware import pending_migrations
        self.assertEqual(pending_migrations(), [])

    def test_course_without_slug_still_gets_a_working_url(self):
        c = make_course("CORE", title="No Slug Yet")
        CourseTrack.objects.filter(pk=c.pk).update(slug=None)
        c.refresh_from_db()
        self.assertEqual(c.get_absolute_url(), "/courses/no-slug-yet/")
