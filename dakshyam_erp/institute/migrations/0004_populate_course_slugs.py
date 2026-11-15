from django.db import migrations
from django.utils.text import slugify


def fill_slugs(apps, schema_editor):
    CourseTrack = apps.get_model("institute", "CourseTrack")
    used = set(CourseTrack.objects.exclude(slug__isnull=True).values_list("slug", flat=True))
    for course in CourseTrack.objects.filter(slug__isnull=True).order_by("id"):
        base = slugify(course.title)[:120] or course.code.lower()
        slug, n = base, 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1
        used.add(slug)
        course.slug = slug
        course.save(update_fields=["slug"])


class Migration(migrations.Migration):
    dependencies = [("institute", "0003_portal_features")]
    operations = [migrations.RunPython(fill_slugs, migrations.RunPython.noop)]
