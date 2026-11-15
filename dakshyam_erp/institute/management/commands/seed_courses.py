from decimal import Decimal

from django.core.management.base import BaseCommand

from institute.models import CourseTrack

DEFAULTS = [
    ("CORE", "Core Code: Programming & Logic", "3M", False,
     "Build strong programming fundamentals and problem-solving skills with C, C++, Python and JavaScript."),
    ("WEB", "Full-Stack Web Development", "3M", False,
     "Learn HTML, CSS, JavaScript and Django or MERN to build and deploy complete web applications."),
    ("APP", "Mobile App Development (Flutter)", "3M", False,
     "Create Android and iOS apps with Flutter and Dart, from first screen to finished project."),
    ("IOT", "IoT & Robotics", "3M", True,
     "Hands-on electronics with ESP32, Arduino and sensors: build connected devices and robots."),
    ("AI_IOT", "Web Dev + IoT + Applied AI", "3M", True,
     "Combine web development, IoT hardware and applied AI to build real, working smart projects."),
    ("VOC", "Vocational Computer Literacy", "15D", False,
     "Practical computer skills for school students, aligned with the NEP 2020 vocational framework."),
]


class Command(BaseCommand):
    help = "Create the standard course tracks if they do not exist. Fees are left at 0 - set them in the admin."

    def handle(self, *args, **options):
        created = 0
        for code, title, duration, kit, summary in DEFAULTS:
            _, was_created = CourseTrack.objects.get_or_create(
                code=code,
                defaults={
                    "title": title,
                    "duration": duration,
                    "total_fee": Decimal("0"),
                    "includes_robotics_kit": kit,
                    "summary": summary,
                },
            )
            created += was_created
        self.stdout.write(self.style.SUCCESS(f"{created} track(s) created, {len(DEFAULTS) - created} already existed."))
        if created:
            self.stdout.write(self.style.WARNING("Set the real fee for each track in /admin/ before admitting students."))
