import logging
from datetime import timedelta

from django.utils import timezone

from .models import (
    MigrainePrediction,
    SinusitisPrediction,
    HayFeverPrediction,
    Location,
)
from .email_sender import EmailSender

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Combined-notification orchestrator.

    Exposes a single deep entry point, check_and_send_combined_notifications,
    which groups predictions by user across all locations and sends one email
    per user. Email rendering/sending, preference checks, and weather-factor
    explanations live in their own modules (EmailSender, NotificationPreferences,
    WeatherFactorExplainer) and are used directly by their respective callers.
    """

    @staticmethod
    def check_and_send_combined_notifications(migraine_predictions: dict, sinusitis_predictions: dict,
                                              hayfever_predictions: dict = None):
        """
        Check migraine, sinusitis, and hay fever predictions and send combined notifications.

        Groups predictions by user across ALL locations and sends one email per user.

        Args:
            migraine_predictions: Dict mapping location IDs to migraine prediction data
            sinusitis_predictions: Dict mapping location IDs to sinusitis prediction data
            hayfever_predictions: Dict mapping location IDs to hay fever prediction data

        Returns:
            int: Number of notifications sent (one per user)
        """
        from django.db.models import Max

        hayfever_predictions = hayfever_predictions or {}

        now = timezone.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        # --- Batch-load all relevant data ---
        locations = Location.objects.select_related("user", "user__health_profile").all()

        user_map = {}
        user_locations = {}
        for location in locations:
            if not location.user:
                continue
            uid = location.user_id
            if uid not in user_map:
                user_map[uid] = location.user
                user_locations[uid] = []
            user_locations[uid].append(location)

        if not user_map:
            return 0

        user_ids = list(user_map.keys())

        # Batch-check daily limits
        users_with_migraine_today = set(
            MigrainePrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=start_of_day,
                prediction_time__lt=end_of_day,
            ).values_list("user_id", flat=True).distinct()
        )
        users_with_sinusitis_today = set(
            SinusitisPrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=start_of_day,
                prediction_time__lt=end_of_day,
            ).values_list("user_id", flat=True).distinct()
        )
        users_with_hayfever_today = set(
            HayFeverPrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=start_of_day,
                prediction_time__lt=end_of_day,
            ).values_list("user_id", flat=True).distinct()
        )

        # Batch-check frequency
        migraine_recent_times = dict(
            MigrainePrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=now - timedelta(hours=24),
            ).values("user_id").annotate(latest=Max("prediction_time")).values_list("user_id", "latest")
        )
        sinusitis_recent_times = dict(
            SinusitisPrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=now - timedelta(hours=24),
            ).values("user_id").annotate(latest=Max("prediction_time")).values_list("user_id", "latest")
        )
        hayfever_recent_times = dict(
            HayFeverPrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=now - timedelta(hours=24),
            ).values("user_id").annotate(latest=Max("prediction_time")).values_list("user_id", "latest")
        )

        # --- Per-user filtering ---
        user_predictions = {}

        for uid, user in user_map.items():
            profile = getattr(user, "health_profile", None)

            if profile and profile.notification_mode == "DIGEST":
                logger.debug(f"Skipping DIGEST mode user {user.username} (predictions run via digest task)")
                continue

            limit = int(profile.daily_notification_limit) if profile else 1
            if limit <= 0:
                logger.debug(f"Notifications disabled for user {user.username} (limit={limit})")
                continue

            emails_sent_today = 1 if (
                uid in users_with_migraine_today
                or uid in users_with_sinusitis_today
                or uid in users_with_hayfever_today
            ) else 0
            if emails_sent_today >= limit:
                logger.debug(f"User {user.username} has reached daily limit ({limit})")
                continue

            notification_frequency_hours = int(profile.notification_frequency_hours) if profile else 3
            frequency_cutoff = now - timedelta(hours=notification_frequency_hours)

            latest_times = [
                t for t in (
                    migraine_recent_times.get(uid),
                    sinusitis_recent_times.get(uid),
                    hayfever_recent_times.get(uid),
                ) if t is not None
            ]
            most_recent_time = max(latest_times) if latest_times else None

            if most_recent_time and most_recent_time >= frequency_cutoff:
                hours_since = (now - most_recent_time).total_seconds() / 3600
                logger.debug(
                    f"User {user.username} was notified {hours_since:.1f} hours ago, "
                    f"minimum frequency is {notification_frequency_hours} hours"
                )
                continue

            if profile and not profile.email_notifications_enabled:
                logger.info(f"Skipping notifications for user {user.username}: Email notifications disabled")
                continue

            # Collect predictions for ALL locations
            user_migraine_preds = []
            user_sinusitis_preds = []
            user_hayfever_preds = []
            migraine_enabled = profile.migraine_predictions_enabled if profile else True
            sinusitis_enabled = profile.sinusitis_predictions_enabled if profile else True
            hayfever_enabled = profile.hay_fever_predictions_enabled if profile else True

            for loc in user_locations[uid]:
                if migraine_enabled:
                    migraine_data = migraine_predictions.get(loc.id)
                    if migraine_data:
                        prob_level = migraine_data.get("probability")
                        pred = migraine_data.get("prediction")
                        if prob_level in ["HIGH", "MEDIUM"] and pred and not pred.notification_sent:
                            user_migraine_preds.append(pred)

                if sinusitis_enabled:
                    sinusitis_data = sinusitis_predictions.get(loc.id)
                    if sinusitis_data:
                        prob_level = sinusitis_data.get("probability")
                        pred = sinusitis_data.get("prediction")
                        if prob_level in ["HIGH", "MEDIUM"] and pred and not pred.notification_sent:
                            user_sinusitis_preds.append(pred)

                if hayfever_enabled:
                    hayfever_data = hayfever_predictions.get(loc.id)
                    if hayfever_data:
                        prob_level = hayfever_data.get("probability")
                        pred = hayfever_data.get("prediction")
                        if prob_level in ["HIGH", "MEDIUM"] and pred and not pred.notification_sent:
                            user_hayfever_preds.append(pred)

            if user_migraine_preds or user_sinusitis_preds or user_hayfever_preds:
                user_predictions[uid] = {
                    "migraine": user_migraine_preds,
                    "sinusitis": user_sinusitis_preds,
                    "hayfever": user_hayfever_preds,
                }

        # --- Send one email per user ---
        notifications_sent = 0

        for uid, predictions in user_predictions.items():
            migraine_preds = predictions["migraine"]
            sinusitis_preds = predictions["sinusitis"]
            hayfever_preds = predictions.get("hayfever", [])

            if not migraine_preds and not sinusitis_preds and not hayfever_preds:
                continue

            user = user_map[uid]

            if EmailSender().send_combined_alert(
                migraine_predictions=migraine_preds,
                sinusitis_predictions=sinusitis_preds,
                hayfever_predictions=hayfever_preds,
            ):
                # Batch-update notification_sent
                all_preds_to_update = []
                for pred in migraine_preds:
                    pred.notification_sent = True
                    all_preds_to_update.append(pred)
                for pred in sinusitis_preds:
                    pred.notification_sent = True
                    all_preds_to_update.append(pred)
                for pred in hayfever_preds:
                    pred.notification_sent = True
                    all_preds_to_update.append(pred)

                if migraine_preds:
                    MigrainePrediction.objects.filter(
                        id__in=[p.id for p in migraine_preds]
                    ).update(notification_sent=True)
                if sinusitis_preds:
                    SinusitisPrediction.objects.filter(
                        id__in=[p.id for p in sinusitis_preds]
                    ).update(notification_sent=True)
                if hayfever_preds:
                    HayFeverPrediction.objects.filter(
                        id__in=[p.id for p in hayfever_preds]
                    ).update(notification_sent=True)

                notifications_sent += 1

                location_count = len(set(
                    p.location_id for p in migraine_preds + sinusitis_preds + hayfever_preds
                ))
                logger.info(
                    f"Sent combined alert to {user.email} covering {location_count} location(s) "
                    f"({len(migraine_preds)} migraine, {len(sinusitis_preds)} sinusitis, "
                    f"{len(hayfever_preds)} hay fever)"
                )

        logger.info(f"Sent {notifications_sent} combined alert notifications")
        return notifications_sent
