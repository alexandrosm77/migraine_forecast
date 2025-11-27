from django.db import models
from django.contrib.auth.models import User
from django.db.models import JSONField
import os


class UserHealthProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="health_profile")
    age = models.PositiveIntegerField(null=True, blank=True)
    prior_conditions = models.TextField(
        blank=True, help_text="Optional: List prior health issues relevant to migraines"
    )
    sensitivity_overall = models.FloatField(
        default=1.0, help_text="Overall sensitivity multiplier (0.5 = less sensitive, 1 = average, 2 = very sensitive)"
    )
    sensitivity_temperature = models.FloatField(default=1.0)
    sensitivity_humidity = models.FloatField(default=1.0)
    sensitivity_pressure = models.FloatField(default=1.0)
    sensitivity_cloud_cover = models.FloatField(default=1.0)
    sensitivity_precipitation = models.FloatField(default=1.0)
    email_notifications_enabled = models.BooleanField(
        default=True, help_text="Enable or disable email notifications for migraine and sinusitis alerts"
    )

    # Prediction service preferences
    migraine_predictions_enabled = models.BooleanField(
        default=True, help_text="Enable or disable migraine predictions for this user"
    )
    sinusitis_predictions_enabled = models.BooleanField(
        default=True, help_text="Enable or disable sinusitis predictions for this user"
    )

    # Notification preferences
    daily_notification_limit = models.IntegerField(
        default=1, help_text="Maximum health alert emails per day for this user (0 = disabled)"
    )
    notification_frequency_hours = models.IntegerField(
        default=3, help_text="Minimum hours between notifications (default: 3 hours). Prevents notification spam."
    )

    # Per-prediction-type notification limits
    daily_migraine_notification_limit = models.IntegerField(
        default=1, help_text="Maximum migraine alert emails per day (0 = use general limit)"
    )
    daily_sinusitis_notification_limit = models.IntegerField(
        default=1, help_text="Maximum sinusitis alert emails per day (0 = use general limit)"
    )

    # Severity threshold for notifications
    SEVERITY_CHOICES = [
        ("MEDIUM", "Medium and High"),
        ("HIGH", "High only"),
    ]
    notification_severity_threshold = models.CharField(
        max_length=10,
        choices=SEVERITY_CHOICES,
        default="MEDIUM",
        help_text="Only send notifications for predictions at or above this severity level",
    )

    # Quiet hours / Do Not Disturb
    quiet_hours_enabled = models.BooleanField(
        default=False, help_text="Enable quiet hours to prevent notifications during specific times"
    )
    quiet_hours_start = models.TimeField(
        null=True, blank=True, help_text="Start of quiet hours (e.g., 22:00 for 10 PM)"
    )
    quiet_hours_end = models.TimeField(null=True, blank=True, help_text="End of quiet hours (e.g., 07:00 for 7 AM)")

    # Digest mode
    NOTIFICATION_MODE_CHOICES = [
        ("IMMEDIATE", "Immediate - Send alerts as they occur"),
        ("DIGEST", "Daily Digest - Send one summary email per day"),
    ]
    notification_mode = models.CharField(
        max_length=20, choices=NOTIFICATION_MODE_CHOICES, default="IMMEDIATE", help_text="How to deliver notifications"
    )
    digest_time = models.TimeField(
        null=True, blank=True, help_text="Time to send daily digest email (e.g., 08:00 for 8 AM)"
    )

    # Last notification tracking (performance optimization)
    last_notification_sent_at = models.DateTimeField(
        null=True, blank=True, help_text="Timestamp of the last notification sent to this user"
    )
    last_migraine_notification_sent_at = models.DateTimeField(
        null=True, blank=True, help_text="Timestamp of the last migraine notification sent"
    )
    last_sinusitis_notification_sent_at = models.DateTimeField(
        null=True, blank=True, help_text="Timestamp of the last sinusitis notification sent"
    )

    prediction_window_start_hours = models.IntegerField(
        default=3, help_text="Start of prediction time window in hours ahead (default: 3 hours)"
    )
    prediction_window_end_hours = models.IntegerField(
        default=6, help_text="End of prediction time window in hours ahead (default: 6 hours)"
    )

    # Language preference
    LANGUAGE_CHOICES = [
        ("en", "English"),
        ("el", "Ελληνικά"),  # Greek
    ]
    language = models.CharField(
        max_length=10,
        choices=LANGUAGE_CHOICES,
        default="en",
        help_text="Preferred language for the user interface and notifications",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Health profile for {self.user.username}"

    def is_in_quiet_hours(self, check_time=None):
        """
        Check if the given time (or current time) falls within quiet hours.

        Args:
            check_time: datetime object to check, defaults to current time

        Returns:
            bool: True if in quiet hours, False otherwise
        """
        if not self.quiet_hours_enabled or not self.quiet_hours_start or not self.quiet_hours_end:
            return False

        from django.utils import timezone

        if check_time is None:
            check_time = timezone.now()

        current_time = check_time.time()

        # Handle quiet hours that span midnight
        if self.quiet_hours_start > self.quiet_hours_end:
            # e.g., 22:00 to 07:00
            return current_time >= self.quiet_hours_start or current_time <= self.quiet_hours_end
        else:
            # e.g., 01:00 to 06:00
            return self.quiet_hours_start <= current_time <= self.quiet_hours_end

    def should_send_notification(self, severity_level):
        """
        Check if a notification should be sent based on severity threshold.

        Args:
            severity_level: "LOW", "MEDIUM", or "HIGH"

        Returns:
            bool: True if notification should be sent, False otherwise
        """
        if severity_level == "LOW":
            return False

        if self.notification_severity_threshold == "HIGH":
            return severity_level == "HIGH"

        # Default: MEDIUM threshold allows both MEDIUM and HIGH
        return severity_level in ["MEDIUM", "HIGH"]


class Location(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="locations")
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    latitude = models.FloatField()
    longitude = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.city}, {self.country}"


class LocationNotificationPreference(models.Model):
    """
    Per-location notification preferences.
    Allows users to customize notification settings for specific locations.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="location_notification_preferences")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="notification_preferences")

    # Location-specific settings
    notifications_enabled = models.BooleanField(
        default=True, help_text="Enable or disable notifications for this specific location"
    )
    priority = models.IntegerField(
        default=1,
        help_text="Priority level for this location (1=low, 5=high). Higher priority locations are included "
        "first if limits apply.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [["user", "location"]]
        verbose_name = "Location Notification Preference"
        verbose_name_plural = "Location Notification Preferences"

    def __str__(self):
        return f"Notification preferences for {self.user.username} - {self.location}"


class WeatherForecast(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="forecasts")
    forecast_time = models.DateTimeField()  # Time when forecast was made
    target_time = models.DateTimeField()  # Time for which forecast is predicting
    temperature = models.FloatField()
    humidity = models.FloatField()
    pressure = models.FloatField()
    wind_speed = models.FloatField()
    precipitation = models.FloatField()
    cloud_cover = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "target_time"],
                name="unique_location_target_time",
            )
        ]

    def __str__(self):
        return f"Forecast for {self.location} at {self.target_time}"


class ActualWeather(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="actual_weather")
    recorded_time = models.DateTimeField()
    temperature = models.FloatField()
    humidity = models.FloatField()
    pressure = models.FloatField()
    wind_speed = models.FloatField()
    precipitation = models.FloatField()
    cloud_cover = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Actual weather for {self.location} at {self.recorded_time}"


class MigrainePrediction(models.Model):
    PROBABILITY_CHOICES = [
        ("LOW", "Low"),
        ("MEDIUM", "Medium"),
        ("HIGH", "High"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="predictions")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="predictions")
    forecast = models.ForeignKey(WeatherForecast, on_delete=models.CASCADE, related_name="predictions")
    prediction_time = models.DateTimeField(auto_now_add=True)  # When prediction was made
    target_time_start = models.DateTimeField()  # Start of prediction window (3-6 hours)
    target_time_end = models.DateTimeField()  # End of prediction window
    probability = models.CharField(max_length=10, choices=PROBABILITY_CHOICES)
    weather_factors = JSONField(default=dict, null=True, blank=True)
    notification_sent = models.BooleanField(default=False)

    def __str__(self):
        return f"Migraine prediction for {self.user.username} at {self.location} ({self.probability})"


class SinusitisPrediction(models.Model):
    PROBABILITY_CHOICES = [
        ("LOW", "Low"),
        ("MEDIUM", "Medium"),
        ("HIGH", "High"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sinusitis_predictions")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="sinusitis_predictions")
    forecast = models.ForeignKey(WeatherForecast, on_delete=models.CASCADE, related_name="sinusitis_predictions")
    prediction_time = models.DateTimeField(auto_now_add=True)  # When prediction was made
    target_time_start = models.DateTimeField()  # Start of prediction window (3-6 hours)
    target_time_end = models.DateTimeField()  # End of prediction window
    probability = models.CharField(max_length=10, choices=PROBABILITY_CHOICES)
    weather_factors = JSONField(default=dict, null=True, blank=True)
    notification_sent = models.BooleanField(default=False)

    def __str__(self):
        return f"Sinusitis prediction for {self.user.username} at {self.location} ({self.probability})"


class NotificationLog(models.Model):
    """
    Comprehensive log of all notifications sent to users.
    Provides better tracking, analytics, and debugging capabilities.
    """

    NOTIFICATION_TYPE_CHOICES = [
        ("migraine", "Migraine Alert"),
        ("sinusitis", "Sinusitis Alert"),
        ("combined", "Combined Alert"),
        ("digest", "Daily Digest"),
        ("test", "Test Email"),
    ]

    CHANNEL_CHOICES = [
        ("email", "Email"),
        ("sms", "SMS"),
        ("push", "Push Notification"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("sent", "Sent"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
    ]

    # Core fields
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notification_logs")
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPE_CHOICES, db_index=True)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default="email")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)

    # Related predictions (can be multiple for combined/digest notifications)
    migraine_predictions = models.ManyToManyField(MigrainePrediction, blank=True, related_name="notification_logs")
    sinusitis_predictions = models.ManyToManyField(SinusitisPrediction, blank=True, related_name="notification_logs")

    # Notification content
    subject = models.CharField(max_length=500, blank=True)
    recipient = models.CharField(max_length=255, help_text="Email address, phone number, or device ID")

    # Metadata
    severity_level = models.CharField(max_length=10, blank=True, help_text="Highest severity in this notification")
    locations_count = models.IntegerField(default=0, help_text="Number of locations included")
    predictions_count = models.IntegerField(default=0, help_text="Total number of predictions included")

    # Timing
    scheduled_time = models.DateTimeField(null=True, blank=True, help_text="When notification was scheduled to be sent")
    sent_at = models.DateTimeField(
        null=True, blank=True, db_index=True, help_text="When notification was actually sent"
    )

    # Error tracking
    error_message = models.TextField(blank=True, help_text="Error message if sending failed")
    retry_count = models.IntegerField(default=0, help_text="Number of retry attempts")

    # Additional data
    metadata = JSONField(default=dict, null=True, blank=True, help_text="Additional metadata about the notification")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification Log"
        verbose_name_plural = "Notification Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at", "user"]),
            models.Index(fields=["status", "notification_type"]),
        ]

    def __str__(self):
        return (
            f"{self.get_notification_type_display()} to {self.user.username} "
            f"- {self.status} ({self.created_at:%Y-%m-%d %H:%M})"
        )

    def mark_sent(self):
        """Mark notification as successfully sent."""
        from django.utils import timezone

        self.status = "sent"
        self.sent_at = timezone.now()
        self.save()

    def mark_failed(self, error_message):
        """Mark notification as failed with error message."""
        self.status = "failed"
        self.error_message = error_message
        self.retry_count += 1
        self.save()

    def mark_skipped(self, reason):
        """Mark notification as skipped with reason."""
        self.status = "skipped"
        self.error_message = reason
        self.save()


class WeatherComparisonReport(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="comparison_reports")
    forecast = models.ForeignKey(WeatherForecast, on_delete=models.CASCADE, related_name="comparison_reports")
    actual = models.ForeignKey(ActualWeather, on_delete=models.CASCADE, related_name="comparison_reports")
    temperature_diff = models.FloatField()
    humidity_diff = models.FloatField()
    pressure_diff = models.FloatField()
    wind_speed_diff = models.FloatField()
    precipitation_diff = models.FloatField()
    cloud_cover_diff = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comparison report for {self.location} at {self.actual.recorded_time}"


class LLMResponse(models.Model):
    """
    Stores raw and parsed responses from the LLM model used during predictions.
    Can be linked to either migraine or sinusitis predictions.
    """

    PREDICTION_TYPE_CHOICES = [
        ("migraine", "Migraine"),
        ("sinusitis", "Sinusitis"),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="llm_responses")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="llm_responses")

    # Prediction type and references
    prediction_type = models.CharField(
        max_length=20, choices=PREDICTION_TYPE_CHOICES, default="migraine", db_index=True
    )
    migraine_prediction = models.ForeignKey(
        "MigrainePrediction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="llm_responses",
        db_column="prediction_id",
    )
    sinusitis_prediction = models.ForeignKey(
        "SinusitisPrediction", on_delete=models.SET_NULL, null=True, blank=True, related_name="llm_responses"
    )

    # LLM request and response data
    request_payload = JSONField(default=dict, null=True, blank=True)
    response_api_raw = JSONField(default=dict, null=True, blank=True)
    response_parsed = JSONField(default=dict, null=True, blank=True)

    # Extracted fields from LLM response
    probability_level = models.CharField(max_length=10, blank=True)
    original_probability_level = models.CharField(
        max_length=10,
        blank=True,
        help_text="Original LLM classification before confidence-based adjustment"
    )
    confidence = models.FloatField(null=True, blank=True)
    confidence_adjusted = models.BooleanField(
        default=False,
        help_text="Whether the probability level was downgraded due to low confidence"
    )
    rationale = models.TextField(blank=True)
    analysis_text = models.TextField(blank=True)
    prevention_tips = JSONField(default=list, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        loc = getattr(self.location, "city", "Unknown")
        pred_type = self.get_prediction_type_display()
        return f"LLMResponse ({pred_type}) for {loc} at {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def prediction(self):
        """Return the associated prediction (migraine or sinusitis)."""
        if self.prediction_type == "migraine":
            return self.migraine_prediction
        elif self.prediction_type == "sinusitis":
            return self.sinusitis_prediction
        return None


class LLMConfiguration(models.Model):
    """
    Model for LLM configuration.
    Allows storing multiple LLM configurations with only one active at a time.
    Allows runtime configuration through Django admin.
    Falls back to environment variables if not configured.
    """

    name = models.CharField(max_length=200, unique=True, help_text="Unique name for this LLM configuration")
    is_active = models.BooleanField(
        default=False, help_text="Set this configuration as the active one (only one can be active at a time)"
    )
    base_url = models.CharField(
        max_length=500,
        default="http://192.168.0.11:11434",
        help_text="Base URL for the LLM API (OpenAI-compatible endpoint)",
    )
    model = models.CharField(max_length=200, default="ibm/granite4:3b-h", help_text="Model name to use for predictions")
    api_key = models.CharField(
        max_length=500, blank=True, default="", help_text="API key for authentication (leave empty if not required)"
    )
    timeout = models.FloatField(default=240.0, help_text="Request timeout in seconds")
    high_token_budget = models.BooleanField(
        default=False,
        help_text="Use high token budget for LLM prompts (more detailed weather context, hourly tables)"
    )
    confidence_threshold = models.FloatField(
        default=0.8,
        help_text="Minimum confidence level (0-1) required to accept LLM classification. "
                  "Predictions below this threshold are downgraded by one level (e.g., HIGH→MEDIUM)."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "LLM Configuration"
        verbose_name_plural = "LLM Configurations"
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"], condition=models.Q(is_active=True), name="unique_active_llm_config"
            )
        ]

    def __str__(self):
        active_str = " (ACTIVE)" if self.is_active else ""
        return f"{self.name}: {self.model}{active_str}"

    def save(self, *args, **kwargs):
        # If this config is being set as active, deactivate all others
        if self.is_active:
            LLMConfiguration.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        """
        Get the active LLM configuration, creating default if none exists.
        Falls back to environment variables for initial values.
        """
        # Try to get the active configuration
        config = cls.objects.filter(is_active=True).first()

        if config:
            return config

        # If no active config exists, try to get any config and activate it
        config = cls.objects.first()
        if config:
            config.is_active = True
            config.save()
            return config

        # If no configs exist at all, create a default one from environment variables
        config = cls.objects.create(
            name="Default",
            is_active=True,
            base_url=os.getenv("LLM_BASE_URL", "http://192.168.0.11:11434"),
            model=os.getenv("LLM_MODEL", "ibm/granite4:3b-h"),
            api_key=os.getenv("LLM_API_KEY", ""),
            timeout=float(os.getenv("LLM_TIMEOUT", "240.0")),
        )
        return config
