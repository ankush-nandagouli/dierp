from django.db import DatabaseError

from .models import SiteSettings


def center(request):
    """Expose branding (editable by the admin) to every template."""
    try:
        site = SiteSettings.load()
    except DatabaseError:  # e.g. before the first migrate
        site = SiteSettings()
    return {
        "SITE": site,
        "CENTER_NAME": site.name,
        "CENTER_LOCATION": site.location_line,
        "CENTER_ADDRESS": site.address,
    }
