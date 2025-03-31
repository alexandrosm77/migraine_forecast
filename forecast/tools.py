from django.utils import timezone


def ensure_timezone_aware(dt):
    """
    Ensure a datetime object is timezone aware.
    If it's naive, make it aware using the current timezone.
    """
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt
