from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("portal.account_urls")),
    path("", include("portal.urls")),  # public website, accounts, student & trainer portals
    path("", include("institute.urls")),  # staff ERP
]

handler404 = "institute.views.handler404"
handler500 = "institute.views.handler500"

handler403 = "institute.views.handler403"

if settings.SERVE_MEDIA:
    urlpatterns += [
        re_path(r"^%s(?P<path>.*)$" % settings.MEDIA_URL.lstrip("/"), serve, {"document_root": settings.MEDIA_ROOT}),
    ]
