"""Sign-in and password routes. Un-namespaced on purpose: templates use {% url 'login' %} etc."""
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

urlpatterns = [
    path("accounts/login/", views.PortalLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password/change/", auth_views.PasswordChangeView.as_view(
        success_url=reverse_lazy("password_change_done")), name="password_change"),
    path("accounts/password/change/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("accounts/password/reset/", views.SitePasswordResetView.as_view(
        success_url=reverse_lazy("password_reset_done"),
        subject_template_name="registration/password_reset_subject.txt",
        email_template_name="registration/password_reset_email.html"), name="password_reset"),
    path("accounts/password/reset/sent/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("accounts/password/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        success_url=reverse_lazy("password_reset_complete")), name="password_reset_confirm"),
    path("accounts/password/reset/complete/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
