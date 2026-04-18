import logging
from datetime import timedelta

from django.utils import timezone

from .models import NotificationLog

logger = logging.getLogger(__name__)


class NotificationPreferences:
    """
    Handles notification preference checking, notification log management,
    and timestamp tracking for the notification system.
    """

    @staticmethod
    def get_user_language(user):
        """
        Get the user's preferred language.

        Returns:
            str or None: Language code (e.g. "en", "el") or None
        """
        try:
            return user.health_profile.language
        except Exception:
            return None

    @staticmethod
    def should_send_notification(user, severity_level, notification_type="general", is_digest=False):
        """
        Check if a notification should be sent based on all user preferences.

        Args:
            user: User object
            severity_level: "LOW", "MEDIUM", or "HIGH"
            notification_type: "migraine", "sinusitis", "hayfever", or "general"
            is_digest: If True, skip the DIGEST mode check

        Returns:
            tuple: (should_send: bool, reason: str)
        """
        try:
            profile = user.health_profile
        except Exception:
            return True, "No profile found, using defaults"

        if not profile.email_notifications_enabled:
            return False, "Email notifications disabled"

        if profile.notification_mode == "DIGEST" and not is_digest:
            return False, "User is in digest mode"

        if not profile.should_send_notification(severity_level):
            return False, f"Severity {severity_level} below threshold {profile.notification_severity_threshold}"

        if profile.is_in_quiet_hours():
            return False, "Currently in quiet hours"

        now = timezone.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Check overall daily limit
        if profile.daily_notification_limit > 0:
            today_count = NotificationLog.objects.filter(
                user=user, status="sent", sent_at__gte=start_of_day, sent_at__lt=start_of_day + timedelta(days=1)
            ).count()

            if today_count >= profile.daily_notification_limit:
                return False, f"Daily limit reached ({today_count}/{profile.daily_notification_limit})"

        # Check per-type limits
        _type_limit_map = {
            "migraine": ("daily_migraine_notification_limit", "Migraine"),
            "sinusitis": ("daily_sinusitis_notification_limit", "Sinusitis"),
            "hayfever": ("daily_hay_fever_notification_limit", "Hay fever"),
        }

        if notification_type in _type_limit_map:
            attr, label = _type_limit_map[notification_type]
            limit = getattr(profile, attr, 0)
            if limit > 0:
                type_count = NotificationLog.objects.filter(
                    user=user,
                    status="sent",
                    notification_type=notification_type,
                    sent_at__gte=start_of_day,
                    sent_at__lt=start_of_day + timedelta(days=1),
                ).count()
                if type_count >= limit:
                    return False, f"{label} daily limit reached ({type_count}/{limit})"

        # Check notification frequency
        if profile.last_notification_sent_at:
            time_since_last = (now - profile.last_notification_sent_at).total_seconds() / 3600
            if time_since_last < profile.notification_frequency_hours:
                return (
                    False,
                    f"Too soon since last notification ({time_since_last:.1f}h < {profile.notification_frequency_hours}h)",  # noqa: E501
                )

        return True, "All checks passed"

    @staticmethod
    def create_notification_log(user, notification_type, migraine_preds=None,
                                sinusitis_preds=None, hayfever_preds=None):
        """
        Create a notification log entry.

        Returns:
            NotificationLog object
        """
        migraine_preds = migraine_preds or []
        sinusitis_preds = sinusitis_preds or []
        hayfever_preds = hayfever_preds or []

        all_severities = [p.probability for p in migraine_preds + sinusitis_preds + hayfever_preds]
        severity_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        highest_severity = max(all_severities, key=lambda x: severity_order.get(x, 0)) if all_severities else "LOW"

        all_locations = set([p.location for p in migraine_preds + sinusitis_preds + hayfever_preds])

        log = NotificationLog.objects.create(
            user=user,
            notification_type=notification_type,
            channel="email",
            status="pending",
            recipient=user.email,
            severity_level=highest_severity,
            locations_count=len(all_locations),
            predictions_count=len(migraine_preds) + len(sinusitis_preds) + len(hayfever_preds),
            scheduled_time=timezone.now(),
        )

        if migraine_preds:
            log.migraine_predictions.set(migraine_preds)
        if sinusitis_preds:
            log.sinusitis_predictions.set(sinusitis_preds)
        if hayfever_preds:
            log.hayfever_predictions.set(hayfever_preds)

        return log

    @staticmethod
    def update_last_notification_timestamp(user, notification_type):
        """Update the last notification timestamp for a user."""
        try:
            profile = user.health_profile
            now = timezone.now()

            profile.last_notification_sent_at = now

            if notification_type in ["migraine", "combined"]:
                profile.last_migraine_notification_sent_at = now
            if notification_type in ["sinusitis", "combined"]:
                profile.last_sinusitis_notification_sent_at = now
            if notification_type in ["hayfever", "combined"]:
                profile.last_hay_fever_notification_sent_at = now

            profile.save()
        except Exception as e:
            logger.warning(f"Could not update last notification timestamp for user {user.username}: {e}")
