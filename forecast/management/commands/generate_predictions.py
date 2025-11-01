from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from forecast.models import Location, MigrainePrediction, SinusitisPrediction
from forecast.prediction_service import MigrainePredictionService
from forecast.prediction_service_sinusitis import SinusitisPredictionService

import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Generate migraine and sinusitis predictions from existing forecast data (Task 2 of decoupled pipeline)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cleanup-days",
            type=int,
            default=7,
            help="Delete predictions older than this many days (default: 7)",
        )
        parser.add_argument(
            "--skip-cleanup",
            action="store_true",
            help="Skip cleanup of old prediction data",
        )
        parser.add_argument(
            "--location-id",
            type=int,
            help="Only generate predictions for a specific location ID",
        )

    def handle(self, *args, **options):
        """
        Generate predictions from existing forecast data.
        
        This command:
        1. Reads weather forecasts from the database
        2. Generates migraine and sinusitis predictions
        3. Stores predictions in the database
        4. Cleans up old prediction data
        
        This is Task 2 of the decoupled pipeline architecture.
        Recommended schedule: Every 30 minutes
        """
        start_time = timezone.now()
        self.stdout.write(
            self.style.SUCCESS(f"[{start_time}] Starting prediction generation...")
        )

        # Initialize prediction services
        migraine_service = MigrainePredictionService()
        sinusitis_service = SinusitisPredictionService()

        # Get locations to process
        if options.get("location_id"):
            locations = Location.objects.filter(id=options["location_id"])
            if not locations:
                self.stdout.write(
                    self.style.ERROR(f"Location with ID {options['location_id']} not found")
                )
                return
        else:
            locations = Location.objects.all()

        if not locations:
            self.stdout.write(self.style.WARNING("No locations found in database"))
            return

        self.stdout.write(f"Found {len(locations)} location(s) to process")

        # Generate predictions for each location
        total_migraine_predictions = 0
        total_sinusitis_predictions = 0
        high_risk_count = 0
        medium_risk_count = 0
        errors = []

        for location in locations:
            try:
                user = location.user
                self.stdout.write(f"\nProcessing location: {location} (User: {user.username})")

                # Check user preferences
                migraine_enabled = True
                sinusitis_enabled = True

                try:
                    user_profile = user.health_profile
                    migraine_enabled = user_profile.migraine_predictions_enabled
                    sinusitis_enabled = user_profile.sinusitis_predictions_enabled
                except Exception:
                    # If no health profile exists, default to both enabled
                    pass

                # Generate migraine prediction if enabled
                if migraine_enabled:
                    try:
                        probability, prediction = migraine_service.predict_migraine_probability(
                            location=location, user=user
                        )
                        
                        if prediction:
                            total_migraine_predictions += 1
                            self.stdout.write(
                                f"  ✓ Migraine: {probability} risk"
                            )
                            
                            if probability == "HIGH":
                                high_risk_count += 1
                            elif probability == "MEDIUM":
                                medium_risk_count += 1
                        else:
                            self.stdout.write(
                                self.style.WARNING("  ⚠ Migraine: No forecast data available")
                            )
                    except Exception as e:
                        error_msg = f"Error generating migraine prediction for {location}: {str(e)}"
                        errors.append(error_msg)
                        self.stdout.write(self.style.ERROR(f"  ✗ {error_msg}"))
                        logger.error(error_msg, exc_info=True)
                else:
                    self.stdout.write("  - Migraine predictions disabled for user")

                # Generate sinusitis prediction if enabled
                if sinusitis_enabled:
                    try:
                        probability, prediction = sinusitis_service.predict_sinusitis_probability(
                            location=location, user=user
                        )
                        
                        if prediction:
                            total_sinusitis_predictions += 1
                            self.stdout.write(
                                f"  ✓ Sinusitis: {probability} risk"
                            )
                            
                            if probability == "HIGH":
                                high_risk_count += 1
                            elif probability == "MEDIUM":
                                medium_risk_count += 1
                        else:
                            self.stdout.write(
                                self.style.WARNING("  ⚠ Sinusitis: No forecast data available")
                            )
                    except Exception as e:
                        error_msg = f"Error generating sinusitis prediction for {location}: {str(e)}"
                        errors.append(error_msg)
                        self.stdout.write(self.style.ERROR(f"  ✗ {error_msg}"))
                        logger.error(error_msg, exc_info=True)
                else:
                    self.stdout.write("  - Sinusitis predictions disabled for user")

            except Exception as e:
                error_msg = f"Error processing location {location}: {str(e)}"
                errors.append(error_msg)
                self.stdout.write(self.style.ERROR(f"  ✗ {error_msg}"))
                logger.error(error_msg, exc_info=True)

        # Cleanup old predictions
        if not options["skip_cleanup"]:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("Cleaning up old prediction data...")
            
            cleanup_days = options["cleanup_days"]
            cutoff_time = timezone.now() - timedelta(days=cleanup_days)
            
            old_migraine = MigrainePrediction.objects.filter(prediction_time__lt=cutoff_time)
            migraine_count = old_migraine.count()
            old_migraine.delete()
            
            old_sinusitis = SinusitisPrediction.objects.filter(prediction_time__lt=cutoff_time)
            sinusitis_count = old_sinusitis.count()
            old_sinusitis.delete()
            
            total_deleted = migraine_count + sinusitis_count
            if total_deleted > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ Deleted {migraine_count} migraine and {sinusitis_count} sinusitis "
                        f"prediction(s) older than {cleanup_days} days"
                    )
                )
            else:
                self.stdout.write("  No old predictions to delete")

        # Summary
        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()
        
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("PREDICTION GENERATION SUMMARY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Locations processed: {len(locations)}")
        self.stdout.write(f"Migraine predictions: {total_migraine_predictions}")
        self.stdout.write(f"Sinusitis predictions: {total_sinusitis_predictions}")
        self.stdout.write(f"HIGH risk predictions: {high_risk_count}")
        self.stdout.write(f"MEDIUM risk predictions: {medium_risk_count}")
        self.stdout.write(f"Errors: {len(errors)}")
        self.stdout.write(f"Duration: {duration:.2f} seconds")
        self.stdout.write(f"Completed at: {end_time}")
        
        if errors:
            self.stdout.write("\nErrors encountered:")
            for error in errors:
                self.stdout.write(self.style.ERROR(f"  - {error}"))
        
        self.stdout.write("=" * 60)
