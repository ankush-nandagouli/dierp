from django.conf import settings


def center(request):
    """Expose branding values to every template."""
    return {
        "CENTER_NAME": settings.CENTER_NAME,
        "CENTER_LOCATION": settings.CENTER_LOCATION,
        "CENTER_ADDRESS": settings.CENTER_ADDRESS,
    }