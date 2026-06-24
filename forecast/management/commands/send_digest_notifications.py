from django.contrib.auth.models import User
from django.utils import timezone
from datetime import time
import logging
from forecast.models import NotificationLog
from forecast.prediction_service import PredictionService
from forecast.management.commands.base import SilentStdoutCommand
from forecast.notification_intake import NotificationIntake

logger = logging.getLogger(__name__)

# Default digest time (6 AM) for users who haven't set one
DEFAULT_DIGEST_TIME = time(6, 0)


class Command(SilentStdoutCommand):
    help = "Send daily digest emails to users who have digest mode enabled"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force send digest regardless of scheduled time",
        )
        parser.add_argument(
            "--user",
            type=str,
            help="Send digest only to specific user (username)",
        )

    def handle(self, *args, **options):
        force = options.get("force", False)
        specific_user = options.get("user")

        self.stdout.write(self.style.SUCCESS("Starting daily digest notification process..."))
        logger.info("Starting daily digest notification process")

        # Get users with digest mode enabled
        users_query = User.objects.filter(
            health_profile__email_notifications_enabled=True, health_profile__notification_mode="DIGEST"
        ).select_related("health_profile")

        if specific_user:
            users_query = users_query.filter(username=specific_user)

        users = list(users_query)

        if not users:
            self.stdout.write(self.style.WARNING("No users with digest mode enabled"))
            logger.info("No users with digest mode enabled")
            return

        self.stdout.write(f"Found {len(users)} user(s) with digest mode enabled")
        logger.info("Found %d user(s) with digest mode enabled", len(users))

        now = timezone.now()
        current_time = now.time()
        digests_sent = 0

        for user in users:
            try:
                profile = user.health_profile

                # Check if it's time to send digest (unless forced)
                if not force:
                    # Use user's digest time or default to 6 AM
                    digest_time = profile.digest_time or DEFAULT_DIGEST_TIME
                    if not profile.digest_time:
                        self.stdout.write(f"User {user.username} has no digest time set, using default (6 AM)")
                    current_minutes = current_time.hour * 60 + current_time.minute
                    digest_minutes = digest_time.hour * 60 + digest_time.minute

                    # Calculate time difference, handling midnight wraparound
                    # For example: digest_time=23:45 (1425 min), current_time=00:15 (15 min)
                    # Direct diff: |15 - 1425| = 1410 (wrong)
                    # Wraparound diff: 1440 - 1410 = 30 (correct)
                    direct_diff = abs(current_minutes - digest_minutes)
                    wraparound_diff = 1440 - direct_diff  # 1440 = 24 * 60 minutes in a day
                    time_diff = min(direct_diff, wraparound_diff)

                    if time_diff > 30:  # More than 30 minutes difference
                        self.stdout.write(
                            f"Skipping {user.username}: not digest time yet "
                            f"(scheduled: {digest_time}, current: {current_time})"
                        )
                        continue

                # Check if digest was already sent today
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                digest_sent_today = NotificationLog.objects.filter(
                    user=user, notification_type="digest", status="sent", sent_at__gte=start_of_day
                ).exists()

                if digest_sent_today and not force:
                    self.stdout.write(f"Digest already sent today for {user.username}")
                    continue

                # Generate predictions for the next 24 hours (fixed window,
                # ignoring user's custom prediction_window settings).
                migraine_service = PredictionService.for_condition("migraine")
                sinusitis_service = PredictionService.for_condition("sinusitis")
                hayfever_service = PredictionService.for_condition("hayfever")

                migraine_preds = []
                sinusitis_preds = []
                hayfever_preds = []

                for location in user.locations.all():
                    if profile.migraine_predictions_enabled:
                        try:
                            prob, pred = migraine_service.predict(
                                location=location,
                                user=user,
                                store_prediction=True,
                                window_start_hours=0,
                                window_end_hours=24,
                            )
                            if pred and prob in ["MEDIUM", "HIGH"]:
                                migraine_preds.append(pred)
                        except Exception as e:
                            self.stdout.write(
                                self.style.ERROR(
                                    f"Error generating migraine prediction for " f"{user.username}/{location}: {e}"
                                )
                            )
                            logger.error(
                                "Digest migraine prediction error for %s/%s: %s",
                                user.username,
                                location,
                                e,
                                exc_info=True,
                            )

                    if profile.sinusitis_predictions_enabled:
                        try:
                            prob, pred = sinusitis_service.predict(
                                location=location,
                                user=user,
                                store_prediction=True,
                                window_start_hours=0,
                                window_end_hours=24,
                            )
                            if pred and prob in ["MEDIUM", "HIGH"]:
                                sinusitis_preds.append(pred)
                        except Exception as e:
                            self.stdout.write(
                                self.style.ERROR(
                                    f"Error generating sinusitis prediction for " f"{user.username}/{location}: {e}"
                                )
                            )
                            logger.error(
                                "Digest sinusitis prediction error for %s/%s: %s",
                                user.username,
                                location,
                                e,
                                exc_info=True,
                            )

                    if profile.hay_fever_predictions_enabled:
                        try:
                            prob, pred = hayfever_service.predict(
                                location=location,
                                user=user,
                                store_prediction=True,
                                window_start_hours=0,
                                window_end_hours=24,
                            )
                            if pred and prob in ["MEDIUM", "HIGH"]:
                                hayfever_preds.append(pred)
                        except Exception as e:
                            self.stdout.write(
                                self.style.ERROR(
                                    f"Error generating hay fever prediction for " f"{user.username}/{location}: {e}"
                                )
                            )
                            logger.error(
                                "Digest hay fever prediction error for %s/%s: %s",
                                user.username,
                                location,
                                e,
                                exc_info=True,
                            )

                # Apply severity threshold
                if profile.notification_severity_threshold == "HIGH":
                    migraine_preds = [p for p in migraine_preds if p.probability == "HIGH"]
                    sinusitis_preds = [p for p in sinusitis_preds if p.probability == "HIGH"]
                    hayfever_preds = [p for p in hayfever_preds if p.probability == "HIGH"]

                # Skip if no predictions
                if not migraine_preds and not sinusitis_preds and not hayfever_preds:
                    self.stdout.write(f"No predictions to send for {user.username}")
                    continue

                # Send digest email
                if self.send_digest_email(user, migraine_preds, sinusitis_preds, hayfever_preds):
                    digests_sent += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Sent digest to {user.username} "
                            f"({len(migraine_preds)} migraine, {len(sinusitis_preds)} sinusitis, "
                            f"{len(hayfever_preds)} hay fever)"
                        )
                    )
                else:
                    self.stdout.write(self.style.ERROR(f"Failed to send digest to {user.username}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing digest for {user.username}: {e}"))
                logger.error("Error processing digest for %s: %s", user.username, e, exc_info=True)

        self.stdout.write(self.style.SUCCESS(f"Digest notification process complete. Sent {digests_sent} digest(s)"))
        logger.info("Digest notification process complete: sent=%d, total_users=%d", digests_sent, len(users))

    def send_digest_email(self, user, migraine_preds, sinusitis_preds, hayfever_preds=None):
        """Send a daily digest email through NotificationIntake."""
        plan = NotificationIntake().send_digest(
            user,
            migraine_predictions=migraine_preds,
            sinusitis_predictions=sinusitis_preds,
            hayfever_predictions=hayfever_preds or [],
        )
        if plan.summary.get("sent", 0) == 1:
            logger.info("Sent daily digest to %s", user.email)
            return True
        reason = plan.items[0].reason if plan.items else "No digest notification planned"
        logger.info("Skipped daily digest for %s: %s", user.email, reason)
        return False
