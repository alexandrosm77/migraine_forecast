from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from datetime import timedelta
import logging

from forecast.models import MigrainePrediction, SinusitisPrediction, NotificationLog

logger = logging.getLogger(__name__)


class Command(BaseCommand):
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

        # Get users with digest mode enabled
        users_query = User.objects.filter(
            health_profile__email_notifications_enabled=True, health_profile__notification_mode="DIGEST"
        ).select_related("health_profile")

        if specific_user:
            users_query = users_query.filter(username=specific_user)

        users = list(users_query)

        if not users:
            self.stdout.write(self.style.WARNING("No users with digest mode enabled"))
            return

        self.stdout.write(f"Found {len(users)} user(s) with digest mode enabled")

        now = timezone.now()
        current_time = now.time()
        digests_sent = 0

        for user in users:
            try:
                profile = user.health_profile

                # Check if it's time to send digest (unless forced)
                if not force:
                    if not profile.digest_time:
                        self.stdout.write(self.style.WARNING(f"User {user.username} has no digest time set, skipping"))
                        continue

                    # Check if current time is within 30 minutes of digest time
                    digest_time = profile.digest_time
                    time_diff = abs(
                        (current_time.hour * 60 + current_time.minute) - (digest_time.hour * 60 + digest_time.minute)
                    )

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

                # Collect predictions from the last 24 hours that haven't been sent
                yesterday = now - timedelta(hours=24)

                migraine_preds = (
                    MigrainePrediction.objects.filter(
                        user=user, prediction_time__gte=yesterday, notification_sent=False
                    )
                    .select_related("location", "forecast")
                    .order_by("-prediction_time")
                )

                # Filter by severity threshold
                if profile.notification_severity_threshold == "HIGH":
                    migraine_preds = migraine_preds.filter(probability="HIGH")
                else:
                    migraine_preds = migraine_preds.filter(probability__in=["MEDIUM", "HIGH"])

                sinusitis_preds = (
                    SinusitisPrediction.objects.filter(
                        user=user, prediction_time__gte=yesterday, notification_sent=False
                    )
                    .select_related("location", "forecast")
                    .order_by("-prediction_time")
                )

                # Filter by severity threshold
                if profile.notification_severity_threshold == "HIGH":
                    sinusitis_preds = sinusitis_preds.filter(probability="HIGH")
                else:
                    sinusitis_preds = sinusitis_preds.filter(probability__in=["MEDIUM", "HIGH"])

                migraine_preds = list(migraine_preds)
                sinusitis_preds = list(sinusitis_preds)

                # Skip if no predictions
                if not migraine_preds and not sinusitis_preds:
                    self.stdout.write(f"No predictions to send for {user.username}")
                    continue

                # Send digest email
                if self.send_digest_email(user, migraine_preds, sinusitis_preds):
                    # Mark predictions as sent
                    for pred in migraine_preds:
                        pred.notification_sent = True
                        pred.save()
                    for pred in sinusitis_preds:
                        pred.notification_sent = True
                        pred.save()

                    digests_sent += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Sent digest to {user.username} "
                            f"({len(migraine_preds)} migraine, {len(sinusitis_preds)} sinusitis)"
                        )
                    )
                else:
                    self.stdout.write(self.style.ERROR(f"Failed to send digest to {user.username}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing digest for {user.username}: {e}"))
                logger.error(f"Error processing digest for {user.username}: {e}", exc_info=True)

        self.stdout.write(self.style.SUCCESS(f"Digest notification process complete. Sent {digests_sent} digest(s)"))

    def send_digest_email(self, user, migraine_preds, sinusitis_preds):
        """Send a daily digest email to a user."""
        from forecast.notification_service import NotificationService

        notification_service = NotificationService()

        # Create notification log
        notification_log = notification_service._create_notification_log(
            user, "digest", migraine_preds=migraine_preds, sinusitis_preds=sinusitis_preds
        )

        if not user.email:
            notification_log.mark_skipped("No email address")
            return False

        # Group predictions by location
        from collections import defaultdict

        location_data = defaultdict(lambda: {"migraine": [], "sinusitis": []})

        for pred in migraine_preds:
            location_data[pred.location.id]["location"] = pred.location
            location_data[pred.location.id]["migraine"].append(pred)

        for pred in sinusitis_preds:
            location_data[pred.location.id]["location"] = pred.location
            location_data[pred.location.id]["sinusitis"].append(pred)

        # Prepare context for email template
        context = {
            "user": user,
            "location_data": list(location_data.values()),
            "migraine_count": len(migraine_preds),
            "sinusitis_count": len(sinusitis_preds),
            "total_count": len(migraine_preds) + len(sinusitis_preds),
            "digest_date": timezone.now().date(),
        }

        subject = f"Daily Health Digest - {len(location_data)} Location(s)"

        # Render email (you'll need to create this template)
        html_message = render_to_string("forecast/email/daily_digest.html", context)
        plain_message = strip_tags(html_message)

        notification_log.subject = subject
        notification_log.save()

        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )

            notification_log.mark_sent()
            notification_service._update_last_notification_timestamp(user, "combined")

            logger.info(f"Sent daily digest to {user.email}")
            return True

        except Exception as e:
            notification_log.mark_failed(str(e))
            logger.error(f"Failed to send daily digest to {user.email}: {e}")
            return False
