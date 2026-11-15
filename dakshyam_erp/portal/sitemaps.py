from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from institute.models import CourseTrack


class StaticPages(Sitemap):
    changefreq = "monthly"
    priority = 0.7

    def items(self):
        return ["portal:home", "portal:course_list", "portal:contact", "portal:register"]

    def location(self, name):
        return reverse(name)

    def priority_for(self, name):
        return 1.0 if name == "portal:home" else 0.7


class CoursePages(Sitemap):
    changefreq = "monthly"
    priority = 0.8

    def items(self):
        return CourseTrack.objects.filter(is_published=True).order_by("code")
