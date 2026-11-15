"""Show a clear "set up the database" page instead of a raw `no such table` crash."""
import html

from django.conf import settings
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpResponse


def pending_migrations():
    """Names of migrations that exist in the code but are not applied to the database."""
    try:
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        return [f"{m.app_label}.{m.name}" for m, _backwards in plan]
    except DatabaseError:
        return ["(database not reachable)"]


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Database setup needed</title>
<style>body{{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:2rem}}
.box{{max-width:680px;margin:3rem auto;background:#fff;color:#0f172a;border-radius:16px;padding:2rem}}
code,pre{{background:#f1f5f9;border-radius:8px;padding:.15rem .4rem;font-size:.95rem}}pre{{padding:1rem;overflow:auto}}
h1{{margin-top:0}}small{{color:#64748b}}</style></head><body><div class="box">
<h1>The database needs to be set up</h1>{body}</div></body></html>"""

DEBUG_BODY = """<p>The code has <strong>{count}</strong> database change(s) that have not been applied to
<code>{db}</code> yet, so pages cannot load. This is a one-time step. Stop the server (Ctrl+C) and run:</p>
<pre>python manage.py migrate
python manage.py seed_courses
python manage.py createsuperuser</pre>
<p>Then start the server again. <small>(<code>createsuperuser</code> is only needed if you have no admin login yet.
<code>seed_courses</code> adds the standard course tracks and is safe to repeat.)</small></p>
<p><small>Pending: {names}</small></p>"""

PROD_BODY = "<p>This site is being updated. Please try again in a few minutes.</p>"


class MigrationCheckMiddleware:
    _ok = False  # once the database is up to date we stop checking

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not MigrationCheckMiddleware._ok:
            pending = pending_migrations()
            if pending:
                if settings.DEBUG:
                    body = DEBUG_BODY.format(
                        count=len(pending), db=html.escape(str(connection.settings_dict["NAME"])),
                        names=html.escape(", ".join(pending[:8]) + (" ..." if len(pending) > 8 else "")),
                    )
                else:
                    body = PROD_BODY
                response = HttpResponse(PAGE.format(body=body), status=503)
                response["Retry-After"] = "60"
                return response
            MigrationCheckMiddleware._ok = True
        return self.get_response(request)
