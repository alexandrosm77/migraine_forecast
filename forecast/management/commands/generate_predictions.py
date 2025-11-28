from time import sleep

from django.utils import timezone
from datetime import timedelta

from forecast.models import Location, MigrainePrediction, SinusitisPrediction, LLMResponse
from forecast.prediction_service import MigrainePredictionService
from forecast.prediction_service_sinusitis import SinusitisPredictionService
from forecast.management.commands.base import SilentStdoutCommand

import logging
from sentry_sdk import capture_exception, capture_message, set_context, add_breadcrumb, start_transaction, set_tag

logger = logging.getLogger(__name__)


class Command(SilentStdoutCommand):
    help = "Generate migraine and sinusitis predictions from existing forecast data (Task 2 of decoupled pipeline)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cleanup-days",
            type=int,
            default=7,
            help="Delete predictions and LLM responses older than this many days (default: 7)",
        )
        parser.add_argument(
            "--skip-cleanup",
            action="store_true",
            help="Skip cleanup of old prediction and LLM response data",
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
        4. Cleans up old prediction and LLM response data

        This is Task 2 of the decoupled pipeline architecture.
        Recommended schedule: Every 30 minutes
        """
        # Start transaction for cron job monitoring
        with start_transaction(op="cron.job", name="generate_predictions"):
            set_tag("cron_job", "generate_predictions")
            set_tag("task", "prediction_generation")

            start_time = timezone.now()
            self.stdout.write(self.style.SUCCESS(f"[{start_time}] Starting prediction generation..."))
            logger.info("Starting prediction generation")

            add_breadcrumb(
                category="cron",
                message="Prediction generation started",
                level="info",
                data={"start_time": str(start_time)},
            )

        # Initialize prediction services
        migraine_service = MigrainePredictionService()
        sinusitis_service = SinusitisPredictionService()

        # Get locations to process
        if options.get("location_id"):
            locations = Location.objects.filter(id=options["location_id"])
            if not locations:
                self.stdout.write(self.style.ERROR(f"Location with ID {options['location_id']} not found"))
                logger.error("Location with ID %s not found", options["location_id"])
                return
        else:
            locations = Location.objects.all()

            if not locations:
                self.stdout.write(self.style.WARNING("No locations found in database"))
                logger.warning("No locations found for prediction generation")
                capture_message("No locations found for prediction generation", level="warning")
                return

            self.stdout.write(f"Found {len(locations)} location(s) to process")
            logger.info("Found %d location(s) to process", len(locations))

            add_breadcrumb(
                category="cron",
                message=f"Processing {len(locations)} locations",
                level="info",
                data={"location_count": len(locations)},
            )

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
                        sleep(5)  # Rate limit to 1 prediction per 5 seconds
                        probability, prediction = migraine_service.predict_migraine_probability(
                            location=location, user=user
                        )

                        if prediction:
                            total_migraine_predictions += 1
                            self.stdout.write(f"  ✓ Migraine: {probability} risk")

                            if probability == "HIGH":
                                high_risk_count += 1
                            elif probability == "MEDIUM":
                                medium_risk_count += 1
                        else:
                            self.stdout.write(self.style.WARNING("  ⚠ Migraine: No forecast data available"))
                    except Exception as e:
                        error_msg = f"Error generating migraine prediction for {location}: {str(e)}"
                        errors.append(error_msg)
                        self.stdout.write(self.style.ERROR(f"  ✗ {error_msg}"))
                        logger.error(error_msg, exc_info=True)

                        # Capture exception with context
                        set_context(
                            "migraine_prediction_error",
                            {"location": str(location), "location_id": location.id, "user": user.username},
                        )
                        capture_exception(e)
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
                            self.stdout.write(f"  ✓ Sinusitis: {probability} risk")

                            if probability == "HIGH":
                                high_risk_count += 1
                            elif probability == "MEDIUM":
                                medium_risk_count += 1
                        else:
                            self.stdout.write(self.style.WARNING("  ⚠ Sinusitis: No forecast data available"))
                    except Exception as e:
                        error_msg = f"Error generating sinusitis prediction for {location}: {str(e)}"
                        errors.append(error_msg)
                        self.stdout.write(self.style.ERROR(f"  ✗ {error_msg}"))
                        logger.error(error_msg, exc_info=True)

                        # Capture exception with context
                        set_context(
                            "sinusitis_prediction_error",
                            {"location": str(location), "location_id": location.id, "user": user.username},
                        )
                        capture_exception(e)
                else:
                    self.stdout.write("  - Sinusitis predictions disabled for user")

            except Exception as e:
                error_msg = f"Error processing location {location}: {str(e)}"
                errors.append(error_msg)
                self.stdout.write(self.style.ERROR(f"  ✗ {error_msg}"))
                logger.error(error_msg, exc_info=True)

                # Capture exception with context
                set_context("prediction_location_error", {"location": str(location), "location_id": location.id})
                capture_exception(e)

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

            # Clean up old LLM responses (same retention period as predictions)
            old_llm_responses = LLMResponse.objects.filter(created_at__lt=cutoff_time)
            llm_count = old_llm_responses.count()
            old_llm_responses.delete()

            total_deleted = migraine_count + sinusitis_count + llm_count
            if total_deleted > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ Deleted {migraine_count} migraine, {sinusitis_count} sinusitis "
                        f"prediction(s), and {llm_count} LLM response(s) older than {cleanup_days} days"
                    )
                )
            else:
                self.stdout.write("  No old predictions or LLM responses to delete")

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

            # Send summary to Sentry
            summary_data = {
                "locations_processed": len(locations),
                "migraine_predictions": total_migraine_predictions,
                "sinusitis_predictions": total_sinusitis_predictions,
                "high_risk_count": high_risk_count,
                "medium_risk_count": medium_risk_count,
                "errors": len(errors),
                "duration_seconds": duration,
                "completed_at": str(end_time),
            }

            add_breadcrumb(category="cron", message="Prediction generation completed", level="info", data=summary_data)

            # Log summary for Promtail/Loki
            logger.info(
                "Prediction generation completed: locations=%d, migraine=%d, sinusitis=%d, high_risk=%d, medium_risk=%d, errors=%d, duration=%.2fs",  # noqa: E501
                len(locations),
                total_migraine_predictions,
                total_sinusitis_predictions,
                high_risk_count,
                medium_risk_count,
                len(errors),
                duration,
            )

            # Alert on high-risk predictions
            if high_risk_count > 0:
                set_tag("high_risk_predictions", high_risk_count)
                logger.info("Generated %d HIGH risk prediction(s)", high_risk_count)
                capture_message(f"Generated {high_risk_count} HIGH risk prediction(s)", level="info")

            if errors:
                self.stdout.write("\nErrors encountered:")
                for error in errors:
                    self.stdout.write(self.style.ERROR(f"  - {error}"))

                # Capture summary message with errors
                logger.warning("Prediction generation completed with %d error(s)", len(errors))
                capture_message(
                    f"Prediction generation completed with {len(errors)} error(s)",
                    level="error" if len(errors) > len(locations) / 2 else "warning",
                )
            else:
                # Capture successful completion
                capture_message(
                    f"Prediction generation completed: {total_migraine_predictions} migraine, {total_sinusitis_predictions} sinusitis",  # noqa: E501
                    level="info",
                )

            self.stdout.write("=" * 60)
