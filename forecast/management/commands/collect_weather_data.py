from django.utils import timezone
from datetime import timedelta

from forecast.models import Location, WeatherForecast
from forecast.weather_service import WeatherService
from forecast.management.commands.base import SilentStdoutCommand

import logging
from sentry_sdk import capture_exception, capture_message, set_context, add_breadcrumb, start_transaction, set_tag

logger = logging.getLogger(__name__)


class Command(SilentStdoutCommand):
    help = "Collect and store weather forecast data for all locations (Task 1 of decoupled pipeline)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cleanup-days",
            type=int,
            default=180,
            help="Delete forecasts older than this many days (default: 180)",
        )
        parser.add_argument(
            "--skip-cleanup",
            action="store_true",
            help="Skip cleanup of old forecast data",
        )

    def handle(self, *args, **options):
        """
        Collect weather forecast data for all locations.

        This command:
        1. Fetches weather forecasts from the API for all locations
        2. Stores/updates forecast data in the database
        3. Cleans up old forecast data to prevent database bloat

        This is Task 1 of the decoupled pipeline architecture.
        Recommended schedule: Every 1-2 hours
        """
        # Start transaction for cron job monitoring
        with start_transaction(op="cron.job", name="collect_weather_data"):
            set_tag("cron_job", "collect_weather_data")
            set_tag("task", "weather_collection")

            start_time = timezone.now()

            # Log to both stdout and logger
            self.stdout.write(self.style.SUCCESS(f"[{start_time}] Starting weather data collection..."))
            logger.info("Starting weather data collection")

            add_breadcrumb(
                category="cron",
                message="Weather data collection started",
                level="info",
                data={"start_time": str(start_time)},
            )

            # Initialize weather service
            weather_service = WeatherService()

            # Get all locations
            locations = Location.objects.all()
            if not locations:
                self.stdout.write(self.style.WARNING("No locations found in database"))
                logger.warning("No locations found for weather data collection")
                capture_message("No locations found for weather data collection", level="warning")
                return

            self.stdout.write(f"Found {len(locations)} location(s) to update")
            logger.info("Found %d location(s) to update", len(locations))

            add_breadcrumb(
                category="cron",
                message=f"Processing {len(locations)} locations",
                level="info",
                data={"location_count": len(locations)},
            )

            # Batch locations into groups of 50
            BATCH_SIZE = 50
            location_list = list(locations)
            total_forecasts_created = 0
            total_forecasts_updated = 0
            errors = []

            # Calculate number of batches
            num_batches = (len(location_list) + BATCH_SIZE - 1) // BATCH_SIZE

            self.stdout.write(
                f"Processing {len(location_list)} locations in {num_batches} batch(es) of up to {BATCH_SIZE}"
            )

            for batch_num in range(num_batches):
                start_idx = batch_num * BATCH_SIZE
                end_idx = min(start_idx + BATCH_SIZE, len(location_list))
                batch_locations = location_list[start_idx:end_idx]

                self.stdout.write(f"\n{'=' * 60}")
                self.stdout.write(f"Processing Batch {batch_num + 1}/{num_batches} ({len(batch_locations)} locations)")
                self.stdout.write(f"{'=' * 60}")

                # Log which locations are in this batch
                batch_location_details = [
                    f"{loc.city}, {loc.country} (User: {loc.user.username}, ID: {loc.id})"
                    for loc in batch_locations
                ]
                self.stdout.write(f"Batch locations: {', '.join(batch_location_details)}")
                logger.info(
                    "Processing batch %d/%d with %d locations: %s",
                    batch_num + 1,
                    num_batches,
                    len(batch_locations),
                    batch_location_details,
                )

                try:
                    # Process batch
                    batch_result = weather_service.update_forecast_for_locations_batch(batch_locations)

                    # Update totals
                    batch_created = batch_result["total_created"]
                    batch_updated = batch_result["total_updated"]
                    batch_errors = batch_result["errors"]

                    total_forecasts_created += batch_created
                    total_forecasts_updated += batch_updated

                    self.stdout.write(
                        f"\nBatch {batch_num + 1} Summary: "
                        f"Created {batch_created}, Updated {batch_updated}, Errors: {len(batch_errors)}"
                    )

                    # Log individual location results
                    for location in batch_locations:
                        loc_result = batch_result["location_results"].get(
                            location.id, {"created": 0, "updated": 0}
                        )
                        created = loc_result["created"]
                        updated = loc_result["updated"]

                        # Check if this location had an error
                        loc_error = next((e for e in batch_errors if e["location"].id == location.id), None)

                        if loc_error:
                            error_msg = f"Error processing location {location}: {loc_error['error']}"
                            errors.append(error_msg)
                            self.stdout.write(self.style.ERROR(f"  ✗ {location} - {loc_error['error']}"))
                            logger.error(error_msg)
                        else:
                            self.stdout.write(
                                f"  ✓ {location} - Created {created}, Updated {updated}"
                            )

                except Exception as e:
                    # Batch-level error
                    error_msg = f"Error processing batch {batch_num + 1}: {str(e)}"
                    errors.append(error_msg)
                    self.stdout.write(self.style.ERROR(f"\n  ✗ {error_msg}"))
                    logger.error(error_msg, exc_info=True)

                    # Capture exception with context
                    set_context(
                        "weather_collection_batch_error",
                        {
                            "batch_num": batch_num + 1,
                            "batch_size": len(batch_locations),
                            "locations": batch_location_details,
                        },
                    )
                    capture_exception(e)

            # Cleanup old forecasts
            if not options["skip_cleanup"]:
                self.stdout.write("\n" + "=" * 60)
                self.stdout.write("Cleaning up old forecast data...")

                cleanup_days = options["cleanup_days"]
                cutoff_time = timezone.now() - timedelta(days=cleanup_days)

                old_forecasts = WeatherForecast.objects.filter(forecast_time__lt=cutoff_time)
                count = old_forecasts.count()

                if count > 0:
                    old_forecasts.delete()
                    self.stdout.write(
                        self.style.SUCCESS(f"  ✓ Deleted {count} forecast(s) older than {cleanup_days} days")
                    )
                else:
                    self.stdout.write("  No old forecasts to delete")

            # Summary
            end_time = timezone.now()
            duration = (end_time - start_time).total_seconds()

            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(self.style.SUCCESS("WEATHER DATA COLLECTION SUMMARY"))
            self.stdout.write("=" * 60)
            self.stdout.write(f"Locations processed: {len(locations)}")
            self.stdout.write(f"Forecasts created: {total_forecasts_created}")
            self.stdout.write(f"Forecasts updated: {total_forecasts_updated}")
            self.stdout.write(f"Errors: {len(errors)}")
            self.stdout.write(f"Duration: {duration:.2f} seconds")
            self.stdout.write(f"Completed at: {end_time}")

            # Send summary to Sentry
            summary_data = {
                "locations_processed": len(locations),
                "forecasts_created": total_forecasts_created,
                "forecasts_updated": total_forecasts_updated,
                "errors": len(errors),
                "duration_seconds": duration,
                "completed_at": str(end_time),
            }

            add_breadcrumb(
                category="cron", message="Weather data collection completed", level="info", data=summary_data
            )

            # Log summary for Promtail/Loki
            logger.info(
                "Weather data collection completed: locations=%d, created=%d, updated=%d, errors=%d, duration=%.2fs",
                len(locations),
                total_forecasts_created,
                total_forecasts_updated,
                len(errors),
                duration,
            )

            if errors:
                self.stdout.write("\nErrors encountered:")
                for error in errors:
                    self.stdout.write(self.style.ERROR(f"  - {error}"))

                # Capture summary message with errors
                logger.warning(
                    "Weather data collection completed with %d error(s)", len(errors)
                )
                capture_message(
                    f"Weather data collection completed with {len(errors)} error(s)",
                    level="error" if len(errors) > len(locations) / 2 else "warning",
                )
            else:
                # Capture successful completion
                capture_message(
                    f"Weather data collection completed successfully: {total_forecasts_created} created, {total_forecasts_updated} updated",  # noqa: E501
                    level="info",
                )

            self.stdout.write("=" * 60)
