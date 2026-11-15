"""Small cache-based throttling for public forms (per-process with the default local-memory cache;
point CACHES at Redis/Memcached to share limits across workers)."""
from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    if settings.TRUST_X_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def is_limited(key, limit):
    return cache.get(key, 0) >= limit


def record(key, window):
    cache.add(key, 0, window)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)


def reset(key):
    cache.delete(key)
