from time import timezone

from django.db import models
from django.contrib.auth.models import User
from django.db.models import JSONField
from django.conf import settings
import os


class UserHealthProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='health_profile')
    age = models.PositiveIntegerField(null=True, blank=True)
    prior_conditions = models.TextField(blank=True, help_text="Optional: List prior health issues relevant to migraines")
    sensitivity_overall = models.FloatField(default=1.0, help_text="Overall sensitivity multiplier (0.5 = less sensitive, 1 = average, 2 = very sensitive)")
    sensitivity_temperature = models.FloatField(default=1.0)
    sensitivity_humidity = models.FloatField(default=1.0)
    sensitivity_pressure = models.FloatField(default=1.0)
    sensitivity_cloud_cover = models.FloatField(default=1.0)
    sensitivity_precipitation = models.FloatField(default=1.0)
    email_notifications_enabled = models.BooleanField(default=True, help_text="Enable or disable email notifications for migraine and sinusitis alerts")

    # Prediction service preferences
    migraine_predictions_enabled = models.BooleanField(default=True, help_text="Enable or disable migraine predictions for this user")
    sinusitis_predictions_enabled = models.BooleanField(default=True, help_text="Enable or disable sinusitis predictions for this user")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Health profile for {self.user.username}"


class Location(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='locations')
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    latitude = models.FloatField()
    longitude = models.FloatField()
    daily_notification_limit = models.IntegerField(default=1, help_text="Maximum migraine alert emails per day for this location (0 = disabled)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.city}, {self.country}"

class WeatherForecast(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='forecasts')
    forecast_time = models.DateTimeField()  # Time when forecast was made
    target_time = models.DateTimeField()    # Time for which forecast is predicting
    temperature = models.FloatField()
    humidity = models.FloatField()
    pressure = models.FloatField()
    wind_speed = models.FloatField()
    precipitation = models.FloatField()
    cloud_cover = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Forecast for {self.location} at {self.target_time}"

class ActualWeather(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='actual_weather')
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
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='predictions')
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='predictions')
    forecast = models.ForeignKey(WeatherForecast, on_delete=models.CASCADE, related_name='predictions')
    prediction_time = models.DateTimeField(auto_now_add=True)  # When prediction was made
    target_time_start = models.DateTimeField()  # Start of prediction window (3-6 hours)
    target_time_end = models.DateTimeField()    # End of prediction window
    probability = models.CharField(max_length=10, choices=PROBABILITY_CHOICES)
    weather_factors = JSONField(default=dict, null=True, blank=True)
    notification_sent = models.BooleanField(default=False)

    def __str__(self):
        return f"Migraine prediction for {self.user.username} at {self.location} ({self.probability})"

class SinusitisPrediction(models.Model):
    PROBABILITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sinusitis_predictions')
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='sinusitis_predictions')
    forecast = models.ForeignKey(WeatherForecast, on_delete=models.CASCADE, related_name='sinusitis_predictions')
    prediction_time = models.DateTimeField(auto_now_add=True)  # When prediction was made
    target_time_start = models.DateTimeField()  # Start of prediction window (3-6 hours)
    target_time_end = models.DateTimeField()    # End of prediction window
    probability = models.CharField(max_length=10, choices=PROBABILITY_CHOICES)
    weather_factors = JSONField(default=dict, null=True, blank=True)
    notification_sent = models.BooleanField(default=False)

    def __str__(self):
        return f"Sinusitis prediction for {self.user.username} at {self.location} ({self.probability})"

class WeatherComparisonReport(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='comparison_reports')
    forecast = models.ForeignKey(WeatherForecast, on_delete=models.CASCADE, related_name='comparison_reports')
    actual = models.ForeignKey(ActualWeather, on_delete=models.CASCADE, related_name='comparison_reports')
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
        ('migraine', 'Migraine'),
        ('sinusitis', 'Sinusitis'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='llm_responses')
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='llm_responses')

    # Prediction type and references
    prediction_type = models.CharField(max_length=20, choices=PREDICTION_TYPE_CHOICES, default='migraine', db_index=True)
    migraine_prediction = models.ForeignKey('MigrainePrediction', on_delete=models.SET_NULL, null=True, blank=True, related_name='llm_responses', db_column='prediction_id')
    sinusitis_prediction = models.ForeignKey('SinusitisPrediction', on_delete=models.SET_NULL, null=True, blank=True, related_name='llm_responses')

    # LLM request and response data
    request_payload = JSONField(default=dict, null=True, blank=True)
    response_api_raw = JSONField(default=dict, null=True, blank=True)
    response_parsed = JSONField(default=dict, null=True, blank=True)

    # Extracted fields from LLM response
    probability_level = models.CharField(max_length=10, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    rationale = models.TextField(blank=True)
    analysis_text = models.TextField(blank=True)
    prevention_tips = JSONField(default=list, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        loc = getattr(self.location, 'city', 'Unknown')
        pred_type = self.get_prediction_type_display()
        return f"LLMResponse ({pred_type}) for {loc} at {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def prediction(self):
        """Return the associated prediction (migraine or sinusitis)."""
        if self.prediction_type == 'migraine':
            return self.migraine_prediction
        elif self.prediction_type == 'sinusitis':
            return self.sinusitis_prediction
        return None


class LLMConfiguration(models.Model):
    """
    Model for LLM configuration.
    Allows storing multiple LLM configurations with only one active at a time.
    Allows runtime configuration through Django admin.
    Falls back to environment variables if not configured.
    """
    name = models.CharField(
        max_length=200,
        unique=True,
        help_text="Unique name for this LLM configuration"
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Set this configuration as the active one (only one can be active at a time)"
    )
    base_url = models.CharField(
        max_length=500,
        default='http://192.168.0.11:11434',
        help_text="Base URL for the LLM API (OpenAI-compatible endpoint)"
    )
    model = models.CharField(
        max_length=200,
        default='ibm/granite4:3b-h',
        help_text="Model name to use for predictions"
    )
    api_key = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text="API key for authentication (leave empty if not required)"
    )
    timeout = models.FloatField(
        default=240.0,
        help_text="Request timeout in seconds"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "LLM Configuration"
        verbose_name_plural = "LLM Configurations"
        constraints = [
            models.UniqueConstraint(
                fields=['is_active'],
                condition=models.Q(is_active=True),
                name='unique_active_llm_config'
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
            name='Default',
            is_active=True,
            base_url=os.getenv('LLM_BASE_URL', 'http://192.168.0.11:11434'),
            model=os.getenv('LLM_MODEL', 'ibm/granite4:3b-h'),
            api_key=os.getenv('LLM_API_KEY', ''),
            timeout=float(os.getenv('LLM_TIMEOUT', '240.0')),
        )
        return config
