"""
Celery tasks for migraine forecast application.
"""

import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


# =============================================================================
# QUEUE: default - General orchestration tasks
# =============================================================================


@shared_task(queue="default")
def collect_weather_data():
    """
    Task 1: Fetch weather data for all locations.
    Runs every 2 hours via Celery Beat.
    """
    from forecast.weather_service import WeatherService
    from forecast.models import Location, WeatherForecast

    logger.info("Starting weather data collection")
    service = WeatherService()
    locations = Location.objects.all()

    if not locations:
        logger.warning("No locations found for weather data collection")
        return {"status": "no_locations"}

    total_created = 0
    total_updated = 0
    errors = []

    # Process locations in batches
    BATCH_SIZE = 50
    location_list = list(locations)
    num_batches = (len(location_list) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num in range(num_batches):
        start_idx = batch_num * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, len(location_list))
        batch_locations = location_list[start_idx:end_idx]

        try:
            batch_result = service.update_forecast_for_locations_batch(batch_locations)
            total_created += batch_result["total_created"]
            total_updated += batch_result["total_updated"]
            errors.extend(batch_result["errors"])
        except Exception as e:
            logger.error(f"Error processing batch {batch_num + 1}: {str(e)}", exc_info=True)
            errors.append(str(e))

    # Cleanup old forecasts (older than 180 days)
    cutoff_time = timezone.now() - timedelta(days=180)
    old_forecasts = WeatherForecast.objects.filter(forecast_time__lt=cutoff_time)
    deleted_count = old_forecasts.count()
    if deleted_count > 0:
        old_forecasts.delete()
        logger.info(f"Deleted {deleted_count} old forecasts")

    logger.info(
        f"Weather data collection completed: locations={len(locations)}, "
        f"created={total_created}, updated={total_updated}, errors={len(errors)}"
    )

    return {
        "status": "completed",
        "locations_processed": len(locations),
        "forecasts_created": total_created,
        "forecasts_updated": total_updated,
        "errors": len(errors),
        "old_forecasts_deleted": deleted_count,
    }


@shared_task(queue="default")
def schedule_immediate_predictions():
    """
    Orchestrator: Queue prediction jobs for IMMEDIATE mode users.
    Runs every 2 hours via Celery Beat (after weather collection).
    """
    from django.contrib.auth.models import User

    logger.info("Scheduling predictions for IMMEDIATE mode users")

    users = (
        User.objects.filter(
            health_profile__notification_mode="IMMEDIATE",
            health_profile__email_notifications_enabled=True,
        )
        .select_related("health_profile")
        .prefetch_related("locations")
    )

    prediction_count = 0

    for user in users:
        profile = user.health_profile
        for location in user.locations.all():
            # Queue predictions for this user/location
            if profile.migraine_predictions_enabled:
                generate_prediction.delay(user.id, location.id, "migraine")
                prediction_count += 1

            if profile.sinusitis_predictions_enabled:
                generate_prediction.delay(user.id, location.id, "sinusitis")
                prediction_count += 1

    logger.info(f"Scheduled {prediction_count} prediction tasks for {len(users)} IMMEDIATE users")

    return {
        "status": "completed",
        "users_processed": len(users),
        "predictions_scheduled": prediction_count,
    }


@shared_task(queue="default")
def schedule_digest_emails():
    """
    Orchestrator: Check for DIGEST users whose digest time has arrived.
    Runs every 15 minutes via Celery Beat.
    """
    from django.contrib.auth.models import User

    logger.info("Checking for DIGEST users ready for email")

    now = timezone.now()
    current_time = now.time()

    # Find users whose digest_time is within the last 15 minutes
    # (to catch users whose digest time fell between checks)
    users = (
        User.objects.filter(
            health_profile__notification_mode="DIGEST",
            health_profile__email_notifications_enabled=True,
        )
        .select_related("health_profile")
        .prefetch_related("locations")
    )

    digest_count = 0

    for user in users:
        profile = user.health_profile
        digest_time = profile.digest_time

        if not digest_time:
            continue

        # Check if digest_time is within the last 15 minutes
        # Handle edge case around midnight
        time_diff_minutes = (current_time.hour * 60 + current_time.minute) - (
            digest_time.hour * 60 + digest_time.minute
        )

        # If within 0-15 minutes past digest time, trigger digest
        if 0 <= time_diff_minutes < 15:
            # Queue digest generation for this user
            send_digest_email.delay(user.id)
            digest_count += 1

    logger.info(f"Scheduled {digest_count} digest emails")

    return {
        "status": "completed",
        "digests_scheduled": digest_count,
    }


@shared_task(queue="default", bind=True, autoretry_for=(Exception,), retry_kwargs={"max_retries": 3, "countdown": 60})
def send_prediction_notification(self, prediction_id, prediction_type):
    """
    Send notification for a prediction if it meets criteria.

    Args:
        prediction_id: ID of the prediction (MigrainePrediction or SinusitisPrediction)
        prediction_type: 'migraine' or 'sinusitis'
    """
    from forecast.models import MigrainePrediction, SinusitisPrediction
    from forecast.notification_service import NotificationService

    logger.info(f"Sending notification for {prediction_type} prediction {prediction_id}")

    # Get the prediction
    if prediction_type == "migraine":
        prediction = MigrainePrediction.objects.get(id=prediction_id)
    else:
        prediction = SinusitisPrediction.objects.get(id=prediction_id)

    # Send notification
    service = NotificationService()
    if prediction_type == "migraine":
        result = service.send_migraine_alert(prediction)
    else:
        result = service.send_sinusitis_alert(prediction)

    return {
        "status": "completed",
        "notification_sent": result,
    }


@shared_task(queue="default", bind=True, autoretry_for=(Exception,), retry_kwargs={"max_retries": 3, "countdown": 60})
def send_digest_email(self, user_id):
    """
    Generate predictions and send digest email for a DIGEST mode user.

    This task:
    1. Generates predictions for all user locations (waking hours window)
    2. Collects all predictions
    3. Sends a combined email with all predictions

    Args:
        user_id: ID of the user
    """
    from django.contrib.auth.models import User
    from forecast.models import MigrainePrediction, SinusitisPrediction
    from forecast.notification_service import NotificationService

    logger.info(f"Generating digest email for user {user_id}")

    user = User.objects.get(id=user_id)
    profile = user.health_profile

    # Generate predictions for all user locations (synchronously)
    # We need to wait for predictions to complete before sending email
    migraine_predictions = []
    sinusitis_predictions = []

    for location in user.locations.all():
        # Generate predictions synchronously (not via Celery)
        # This ensures predictions are ready before we send the email
        if profile.migraine_predictions_enabled:
            # Call the task function directly (not as a Celery task)
            # This runs synchronously in the current worker
            result = generate_digest_predictions(self, user.id, location.id, "migraine")
            if result.get("prediction_id"):
                pred = MigrainePrediction.objects.get(id=result["prediction_id"])
                if pred.probability in ["MEDIUM", "HIGH"]:
                    migraine_predictions.append(pred)

        if profile.sinusitis_predictions_enabled:
            result = generate_digest_predictions(self, user.id, location.id, "sinusitis")
            if result.get("prediction_id"):
                pred = SinusitisPrediction.objects.get(id=result["prediction_id"])
                if pred.probability in ["MEDIUM", "HIGH"]:
                    sinusitis_predictions.append(pred)

    # Send combined email if we have any predictions
    if migraine_predictions or sinusitis_predictions:
        service = NotificationService()
        result = service.send_combined_alert(
            migraine_predictions=migraine_predictions, sinusitis_predictions=sinusitis_predictions
        )

        return {
            "status": "completed",
            "email_sent": result,
            "migraine_count": len(migraine_predictions),
            "sinusitis_count": len(sinusitis_predictions),
        }
    else:
        logger.info(f"No predictions to send for user {user_id}")
        return {
            "status": "completed",
            "email_sent": False,
            "reason": "no_predictions",
        }


@shared_task(queue="default")
def cleanup_old_data():
    """
    Clean up old predictions and LLM responses.
    Runs daily at 3 AM via Celery Beat.
    """
    from forecast.models import MigrainePrediction, SinusitisPrediction, LLMResponse

    logger.info("Starting cleanup of old data")

    # Delete predictions older than 7 days
    cutoff_time = timezone.now() - timedelta(days=7)

    # MigrainePrediction and SinusitisPrediction use 'prediction_time' field
    migraine_deleted = MigrainePrediction.objects.filter(prediction_time__lt=cutoff_time).delete()[0]
    sinusitis_deleted = SinusitisPrediction.objects.filter(prediction_time__lt=cutoff_time).delete()[0]
    # LLMResponse uses 'created_at' field
    llm_deleted = LLMResponse.objects.filter(created_at__lt=cutoff_time).delete()[0]

    logger.info(f"Cleanup completed: migraine={migraine_deleted}, sinusitis={sinusitis_deleted}, llm={llm_deleted}")

    return {
        "status": "completed",
        "migraine_predictions_deleted": migraine_deleted,
        "sinusitis_predictions_deleted": sinusitis_deleted,
        "llm_responses_deleted": llm_deleted,
    }


# =============================================================================
# QUEUE: llm - LLM inference tasks (MUST run serially, concurrency=1)
# =============================================================================


@shared_task(queue="llm", bind=True, autoretry_for=(Exception,), retry_kwargs={"max_retries": 2, "countdown": 120})
def generate_prediction(self, user_id, location_id, prediction_type):
    """
    Generate a single prediction using LLM inference.
    CRITICAL: This task MUST run with concurrency=1 due to LLM API constraints.

    Args:
        user_id: ID of the user
        location_id: ID of the location
        prediction_type: 'migraine' or 'sinusitis'
    """
    from django.contrib.auth.models import User
    from forecast.models import Location
    from forecast.prediction_service import MigrainePredictionService
    from forecast.prediction_service_sinusitis import SinusitisPredictionService

    logger.info(f"Generating {prediction_type} prediction for user {user_id}, location {location_id}")

    user = User.objects.get(id=user_id)
    location = Location.objects.get(id=location_id)

    # Generate prediction for next 2-hour window (0-2 hours ahead)
    # The services use window_start_hours and window_end_hours parameters
    if prediction_type == "migraine":
        service = MigrainePredictionService()
        probability_level, prediction = service.predict_migraine_probability(
            location=location,
            user=user,
            store_prediction=True,
            window_start_hours=0,
            window_end_hours=2
        )
    else:
        service = SinusitisPredictionService()
        probability_level, prediction = service.predict_sinusitis_probability(
            location=location,
            user=user,
            store_prediction=True,
            window_start_hours=0,
            window_end_hours=2
        )

    # Queue notification check (on default queue)
    if prediction:
        send_prediction_notification.delay(prediction.id, prediction_type)

    return {
        "status": "completed",
        "prediction_id": prediction.id if prediction else None,
        "probability_level": probability_level,
    }


@shared_task(queue="llm", bind=True, autoretry_for=(Exception,), retry_kwargs={"max_retries": 2, "countdown": 120})
def generate_digest_predictions(self, user_id, location_id, prediction_type):
    """
    Generate predictions for DIGEST mode user (waking hours window).
    CRITICAL: This task MUST run with concurrency=1 due to LLM API constraints.

    Args:
        user_id: ID of the user
        location_id: ID of the location
        prediction_type: 'migraine' or 'sinusitis'
    """
    from django.contrib.auth.models import User
    from forecast.models import Location
    from forecast.prediction_service import MigrainePredictionService
    from forecast.prediction_service_sinusitis import SinusitisPredictionService
    from datetime import datetime
    import pytz

    logger.info(f"Generating {prediction_type} digest prediction for user {user_id}, location {location_id}")

    user = User.objects.get(id=user_id)
    location = Location.objects.get(id=location_id)

    # Get location timezone
    # Assuming location has a timezone field - if not, default to UTC
    location_tz = pytz.timezone(getattr(location, "timezone", "UTC"))

    # Calculate waking hours window (6 AM - 10 PM in location timezone)
    now_local = timezone.now().astimezone(location_tz)
    today = now_local.date()

    # Start at 6 AM today (or now if it's already past 6 AM)
    waking_start = location_tz.localize(datetime.combine(today, datetime.min.time().replace(hour=6)))
    if now_local > waking_start:
        waking_start = now_local

    # End at 10 PM today
    waking_end = location_tz.localize(datetime.combine(today, datetime.min.time().replace(hour=22)))

    # Calculate hours ahead for the window
    now_utc = timezone.now()
    window_start_hours = int((waking_start - now_utc).total_seconds() / 3600)
    window_end_hours = int((waking_end - now_utc).total_seconds() / 3600)

    # Ensure window is valid (at least 0 hours ahead)
    window_start_hours = max(0, window_start_hours)
    window_end_hours = max(window_start_hours + 1, window_end_hours)

    # Generate prediction for waking hours
    prediction = None
    probability_level = None
    if prediction_type == "migraine":
        service = MigrainePredictionService()
        probability_level, prediction = service.predict_migraine_probability(
            location=location,
            user=user,
            store_prediction=True,
            window_start_hours=window_start_hours,
            window_end_hours=window_end_hours
        )
    else:
        service = SinusitisPredictionService()
        probability_level, prediction = service.predict_sinusitis_probability(
            location=location,
            user=user,
            store_prediction=True,
            window_start_hours=window_start_hours,
            window_end_hours=window_end_hours
        )

    return {
        "status": "completed",
        "prediction_id": prediction.id if prediction else None,
        "probability_level": probability_level,
        "waking_hours": f"{waking_start} to {waking_end}",
    }
