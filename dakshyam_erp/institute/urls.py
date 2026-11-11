from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("admissions/new/", views.create_admission, name="create_admission"),
    path("students/", views.student_directory, name="student_directory"),
    path("students/export/", views.export_students_csv, name="export_students"),
    path("students/<int:student_id>/", views.student_detail, name="student_detail"),
    path("students/<int:student_id>/edit/", views.edit_admission, name="edit_admission"),
    path("kits/", views.kit_tracker, name="kit_tracker"),
    path("kits/toggle/<int:student_id>/", views.toggle_kit_status, name="toggle_kit_status"),
    path("fees/", views.receipt_list, name="receipt_list"),
    path("fees/collect/<int:student_id>/", views.collect_fee, name="collect_fee"),
    path("fees/receipt/<int:receipt_id>/", views.view_receipt, name="view_receipt"),
    path("verify/<uuid:verification_uuid>/", views.verify_receipt, name="verify_receipt"),
]