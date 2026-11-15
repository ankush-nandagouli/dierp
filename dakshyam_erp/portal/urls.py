from django.contrib.sitemaps.views import sitemap
from django.urls import path

from . import views
from .sitemaps import CoursePages, StaticPages

app_name = "portal"

sitemaps = {"pages": StaticPages, "courses": CoursePages}

urlpatterns = [
    # public website
    path("", views.home, name="home"),
    path("courses/", views.course_list, name="course_list"),
    path("courses/<slug:slug>/", views.course_detail, name="course_detail"),
    path("contact/", views.contact, name="contact"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    # registration & verification
    path("register/", views.register, name="register"),
    path("register/done/", views.register_done, name="register_done"),
    path("verify-email/resend/", views.resend_verification, name="resend_verification"),
    path("verify-email/<str:token>/", views.verify_email, name="verify_email"),
    path("verify-id/<str:token>/", views.verify_id, name="verify_id"),
    path("accounts/redirect/", views.after_login, name="after_login"),
    # student portal
    path("student/", views.student_dashboard, name="student_dashboard"),
    path("student/receipts/", views.student_receipts, name="student_receipts"),
    path("student/receipts/<int:receipt_id>/", views.student_receipt, name="student_receipt"),
    path("student/profile/", views.student_profile, name="student_profile"),
    path("student/id-card/", views.student_id_card, name="student_id_card"),
    # trainer portal
    path("trainer/", views.trainer_dashboard, name="trainer_dashboard"),
    path("trainer/profile/", views.trainer_profile, name="trainer_profile"),
    path("trainer/batch/<int:batch_id>/", views.trainer_batch, name="trainer_batch"),
    path("trainer/batch/<int:batch_id>/attendance/", views.trainer_attendance, name="trainer_attendance"),
    path("trainer/batch/<int:batch_id>/report/", views.trainer_report, name="trainer_report"),
]
