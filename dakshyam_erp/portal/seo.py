"""JSON-LD (schema.org) builders for search-engine rich results."""
import json

from django.utils.safestring import mark_safe


def _abs(request, path):
    return request.build_absolute_uri(path)


def organization(request, site):
    data = {
        "@context": "https://schema.org",
        "@type": "EducationalOrganization",
        "name": site.name,
        "url": _abs(request, "/"),
        "description": site.meta_description,
        "address": {
            "@type": "PostalAddress",
            "streetAddress": site.address,
            "addressLocality": site.city,
            "addressRegion": "Madhya Pradesh",
            "addressCountry": "IN",
        },
    }
    if site.logo:
        data["logo"] = _abs(request, site.logo.url)
    if site.phone:
        data["telephone"] = f"+91{site.phone}"
    if site.email:
        data["email"] = site.email
    same_as = [u for u in (site.facebook_url, site.instagram_url, site.youtube_url) if u]
    if same_as:
        data["sameAs"] = same_as
    return data


def course(request, course, site):
    data = {
        "@context": "https://schema.org",
        "@type": "Course",
        "name": course.title,
        "description": course.summary or site.meta_description,
        "url": _abs(request, course.get_absolute_url()),
        "provider": {"@type": "EducationalOrganization", "name": site.name, "url": _abs(request, "/")},
    }
    if site.show_fees and course.total_fee > 0:
        data["offers"] = {"@type": "Offer", "price": str(course.total_fee), "priceCurrency": "INR"}
    return data


def breadcrumbs(request, trail):
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": _abs(request, path)}
            for i, (name, path) in enumerate(trail, start=1)
        ],
    }


def dumps(objs):
    """Safe to embed inside a <script type="application/ld+json"> block."""
    text = json.dumps(objs if len(objs) != 1 else objs[0], ensure_ascii=False)
    return mark_safe(text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))
