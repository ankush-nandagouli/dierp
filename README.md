# Dakshyam ERP

A Django web app for running a training center: student admissions, fee collection with QR-verifiable
receipts, and IoT/robotics kit tracking. Built for the Dakshyam Innovations center in Waraseoni, Balaghat.

## What is in the box

| Area | Who uses it | URLs |
|---|---|---|
| **Public website** - home, course list and course pages, contact, online registration | Anyone | `/`, `/courses/`, `/courses/<slug>/`, `/contact/`, `/register/` |
| **Student portal** - course/batch/trainer, fees, attendance %, fee receipts, edit profile, ID card | Students | `/student/...` |
| **Trainer portal** - own batches, mark attendance, attendance report + CSV, edit profile | Trainers | `/trainer/...` |
| **Staff ERP** - admissions, approvals, fee collection, receipts, directory, kits, logo & website settings | Staff (`is_staff`) | `/dashboard/`, `/students/`, `/fees/`, ... |
| **Django admin** - course content/SEO, batches, trainers, attendance corrections, branding | Superusers / staff | `/admin/` |

Highlights

- **Logo & branding**: upload once (Staff ERP -> *Logo & Website*, or admin -> Site settings); it appears on the public
  site, staff sidebar, receipts, ID cards and social-share previews.
- **Online registration**: validated form (Indian mobile, DOB, name rules, strong password, photo type/size, honeypot,
  rate limit). The applicant gets a **signed, 48-hour email verification link** and cannot sign in until it is used.
  Staff then approve the application (dashboard shows pending ones).
- **Trainer accounts**: created in the admin (*Trainers -> Add*), which also creates the login. A trainer only ever sees
  and marks attendance for the **batches assigned to them** (others return 404).
- **Attendance**: Present / Late / Absent per student per day; no future dates, none before the batch started, and
  trainers can change records only within a configurable window (default 7 days). Admins can correct anything.
- **ID card**: printable CR80 card (front + back) with photo, enrollment number, course, batch, validity and a QR code
  that opens a public verification page showing only name, enrollment no., course and validity.
- **Receipts**: staff receipts as before; students can open and print their own, each with a verification QR code.
- **SEO**: unique title/description/canonical per page, Open Graph + Twitter tags, JSON-LD (EducationalOrganization,
  Course, BreadcrumbList), `sitemap.xml`, `robots.txt`, semantic HTML, a single `<h1>` per page, human URLs
  (`/courses/full-stack-web-development/`), static CSS (no render-blocking scripts). All logged-in pages are `noindex`.
- **Staff ERP** (unchanged features): admissions, fee collection with over-payment protection, student directory with
  live search and CSV export, kit tracker, dashboard.

## Roles and access

| Account | Created by | Can open |
|---|---|---|
| Student | Registers online (or staff click *Invite to Portal* on an existing student) | Own `/student/` pages only |
| Trainer | Admin: *Trainers -> Add* | Own `/trainer/` pages only |
| Staff | Admin: tick *Staff status* | Staff ERP (`/dashboard/` ...) |
| Superuser | `createsuperuser` | Everything, incl. branding settings |

Students and trainers get a **403** on staff pages, and staff/trainers/students cannot open each other's portals.
Everyone signs in at `/accounts/login/` with **email or username** and lands on the right place automatically.

> **Upgrading from the previous version:** staff pages now require the *Staff status* flag. Superusers already have
> it; tick it for any other user who should keep using the staff ERP.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cd dakshyam_erp
python manage.py migrate
python manage.py seed_courses          # creates the 6 standard tracks (fees = 0, set them in /admin/)
python manage.py createsuperuser
python manage.py runserver
```

Open <http://127.0.0.1:8000/> (public site) and <http://127.0.0.1:8000/accounts/login/> to sign in.

First-time setup checklist (all in `/admin/` or the staff sidebar):

1. **Logo & Website** (staff sidebar, superuser): upload the logo, phone, email, address and a 120-160 character
   description for Google.
2. **Course tracks**: set each track's fee, tick *Is published*, and write a *summary* and *description* - this text is
   what appears on the public course pages and in search results.
3. **Trainers -> Add**: create each trainer (this also creates their login).
4. **Batches -> Add**: course + name + timing + trainer. Students are placed in a batch from *Edit* on their record.
5. Online applicants appear on the dashboard; open one, assign a batch and click **Approve Admission**.

In development emails (verification, password reset) are printed in the terminal.

## Updating and troubleshooting

**After copying in a new version, always run the database migration** (Windows PowerShell, virtual environment active):

```powershell
cd dakshyam_erp
pip install -r ..\requirements.txt
python manage.py migrate
python manage.py seed_courses     # safe to repeat; only adds missing standard tracks
python manage.py runserver
```

| Symptom | Cause and fix |
|---|---|
| `OperationalError: no such table: institute_...` or `django_session` | The database file has not been migrated (or is a new, empty file). Run `python manage.py migrate`. The app now shows a setup page with these steps instead of crashing. |
| You can sign in but your old students are gone | You are using a new empty `db.sqlite3`. Put your old database file back in `dakshyam_erp/` **before** running `migrate`; migrations keep existing data. |
| Site is unstyled | `dakshyam_erp/static/portal/css/site.css` is missing; copy the `static` folder. |
| `ModuleNotFoundError: qrcode / PIL / whitenoise` | `pip install -r requirements.txt` inside the virtual environment. |
| 403 on `/dashboard/` for a staff user | Tick *Staff status* for that user in `/admin/`. |
| Verification emails never arrive | In development they are printed in the terminal. In production configure SMTP (see `.env.example`). |

Never commit `db.sqlite3`; it holds student and payment data. Back it up by copying the file.

## Configuration

All settings come from environment variables (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_DEBUG` | `True` | Set `False` in production |
| `DJANGO_SECRET_KEY` | dev key (DEBUG only) | **Required** when DEBUG is off |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hostnames |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | – | e.g. `https://erp.example.com` |
| `DJANGO_DB_PATH` | `dakshyam_erp/db.sqlite3` | SQLite file location |
| `DJANGO_SSL_REDIRECT` | `True` (prod) | Set `False` if TLS is terminated elsewhere without the forwarded-proto header |
| `DJANGO_EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | console backend | **Set SMTP in production**, otherwise nobody can verify their email |
| `DJANGO_SERVE_MEDIA` | `True` in DEBUG | Let Django serve uploaded logo/photos (fine for one small server) |
| `DJANGO_TRUST_X_FORWARDED_FOR` | `False` | Use real client IPs for rate limiting behind your own proxy |

Branding (name, logo, phone, address...) is now edited in the app, not through environment variables.

## Tests

```bash
cd dakshyam_erp
python manage.py test
```

CI (`.github/workflows/ci.yml`) runs checks, a missing-migration guard and the test suite on every push.

## Deployment

```bash
docker build -t dakshyam-erp .
docker run -p 8000:8000 -v erp-data:/data \
  -e DJANGO_SECRET_KEY=... -e DJANGO_ALLOWED_HOSTS=erp.example.com \
  -e DJANGO_CSRF_TRUSTED_ORIGINS=https://erp.example.com dakshyam-erp
```

Notes for production:

- Put it behind a TLS-terminating proxy (nginx / Caddy) that sets `X-Forwarded-Proto`.
- Uploaded files (logo, student/trainer photos) live in `media/`. Either set `DJANGO_SERVE_MEDIA=True` or have your web
  server serve that directory, and persist it with a volume. File names are random so photos cannot be guessed.
- After going live: verify the site in Google Search Console (paste the code into *Logo & Website*) and submit
  `https://your-domain/sitemap.xml`.
- Rate limits (registration, resend, sign-in) use the local cache. With several gunicorn workers each keeps its own
  counters; configure a shared cache (Redis/Memcached) for strict limits.
- SQLite is fine for a single center. Back up the DB file regularly (it holds financial records).
- The receipt QR encodes the URL the receipt was opened on, so print receipts from the production domain.

## Project layout

```
dakshyam_erp/
  dakshyam_erp/        project settings, root URLs
  institute/           data models, staff ERP views, admin, seed_courses command
  portal/              public website, registration, student & trainer portals, SEO, ID cards
  templates/           staff pages (Tailwind) + portal/ (plain-CSS public site and portals)
  static/portal/css/   site stylesheet
```

## Known limitations / roadmap

- The staff ERP pages still load Tailwind/Alpine/HTMX/Lucide from CDNs (the public site and portals use plain CSS).
- Email verification proves the address, not the phone number: there is no SMS/OTP step (needs a paid SMS provider).
- A student record has one course. A second course means a second admission with a different email.
- Students and trainers cannot change their own email or name (the center controls these); staff edit them.
- ID cards are printed / saved as PDF from the browser; there is no server-side PDF or image export.
- No receipt cancellation workflow, certificates or holiday calendar yet.
