from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from forecast.models import Location, MigrainePrediction, SinusitisPrediction
from forecast.notification_service import NotificationService

import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process and send pending notifications for high/medium risk predictions (Task 3 of decoupled pipeline)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be sent without actually sending notifications",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force send notifications even if already sent (for testing)",
        )

    def handle(self, *args, **options):
        """
        Process and send pending notifications.
        
        This command:
        1. Finds unsent HIGH/MEDIUM predictions
        2. Checks user notification limits and preferences
        3. Sends combined notifications (migraine + sinusitis in one email)
        4. Marks notifications as sent
        
        This is Task 3 of the decoupled pipeline architecture.
        Recommended schedule: Every 30 minutes (or more frequently)
        """
        start_time = timezone.now()
        self.stdout.write(
            self.style.SUCCESS(f"[{start_time}] Starting notification processing...")
        )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No notifications will be sent"))

        # Initialize notification service
        notification_service = NotificationService()

        # Get all locations
        locations = Location.objects.all()
        if not locations:
            self.stdout.write(self.style.WARNING("No locations found in database"))
            return

        # Build predictions dictionary grouped by location
        migraine_predictions = {}
        sinusitis_predictions = {}
        
        # Find unsent predictions for each location
        for location in locations:
            # Get recent unsent migraine predictions (last 6 hours)
            recent_time = timezone.now() - timedelta(hours=6)
            
            if options["force"]:
                # For testing: get recent predictions regardless of sent status
                migraine_pred = MigrainePrediction.objects.filter(
                    location=location,
                    prediction_time__gte=recent_time,
                    probability__in=["HIGH", "MEDIUM"]
                ).order_by("-prediction_time").first()
                
                sinusitis_pred = SinusitisPrediction.objects.filter(
                    location=location,
                    prediction_time__gte=recent_time,
                    probability__in=["HIGH", "MEDIUM"]
                ).order_by("-prediction_time").first()
            else:
                # Normal mode: only unsent predictions
                migraine_pred = MigrainePrediction.objects.filter(
                    location=location,
                    prediction_time__gte=recent_time,
                    probability__in=["HIGH", "MEDIUM"],
                    notification_sent=False
                ).order_by("-prediction_time").first()
                
                sinusitis_pred = SinusitisPrediction.objects.filter(
                    location=location,
                    prediction_time__gte=recent_time,
                    probability__in=["HIGH", "MEDIUM"],
                    notification_sent=False
                ).order_by("-prediction_time").first()
            
            # Add to dictionaries if found
            if migraine_pred:
                migraine_predictions[location.id] = {
                    "probability": migraine_pred.probability,
                    "prediction": migraine_pred
                }
            
            if sinusitis_pred:
                sinusitis_predictions[location.id] = {
                    "probability": sinusitis_pred.probability,
                    "prediction": sinusitis_pred
                }

        # Count pending notifications
        total_pending = len(set(list(migraine_predictions.keys()) + list(sinusitis_predictions.keys())))
        
        self.stdout.write(f"Found {len(migraine_predictions)} pending migraine notification(s)")
        self.stdout.write(f"Found {len(sinusitis_predictions)} pending sinusitis notification(s)")
        self.stdout.write(f"Total unique locations with pending notifications: {total_pending}")

        if total_pending == 0:
            self.stdout.write(self.style.SUCCESS("No pending notifications to send"))
            return

        # Display pending notifications
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("PENDING NOTIFICATIONS:")
        self.stdout.write("=" * 60)
        
        all_location_ids = set(list(migraine_predictions.keys()) + list(sinusitis_predictions.keys()))
        for location_id in all_location_ids:
            location = Location.objects.get(id=location_id)
            user = location.user
            
            migraine_info = migraine_predictions.get(location_id)
            sinusitis_info = sinusitis_predictions.get(location_id)
            
            self.stdout.write(f"\n{user.username} ({user.email}) - {location}:")
            
            if migraine_info:
                self.stdout.write(f"  • Migraine: {migraine_info['probability']} risk")
            
            if sinusitis_info:
                self.stdout.write(f"  • Sinusitis: {sinusitis_info['probability']} risk")

        # Send notifications
        if not options["dry_run"]:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("Sending notifications...")
            self.stdout.write("=" * 60)
            
            notifications_sent = notification_service.check_and_send_combined_notifications(
                migraine_predictions, sinusitis_predictions
            )
            
            self.stdout.write(
                self.style.SUCCESS(f"\n✓ Successfully sent {notifications_sent} notification(s)")
            )
        else:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(self.style.WARNING("DRY RUN - Notifications not sent"))
            self.stdout.write("=" * 60)
            notifications_sent = 0

        # Summary
        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()
        
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("NOTIFICATION PROCESSING SUMMARY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Pending migraine notifications: {len(migraine_predictions)}")
        self.stdout.write(f"Pending sinusitis notifications: {len(sinusitis_predictions)}")
        self.stdout.write(f"Notifications sent: {notifications_sent}")
        self.stdout.write(f"Duration: {duration:.2f} seconds")
        self.stdout.write(f"Completed at: {end_time}")
        self.stdout.write("=" * 60)

