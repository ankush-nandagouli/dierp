FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dakshyam_erp/ .

# Build-time only values so collectstatic can import settings; real values come from the environment at runtime.
RUN DJANGO_DEBUG=False DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

ENV DJANGO_DEBUG=False DJANGO_DB_PATH=/data/db.sqlite3
VOLUME ["/data"]
EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn dakshyam_erp.wsgi:application --bind 0.0.0.0:8000 --workers 3"]
