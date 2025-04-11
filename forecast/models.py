from time import timezone

from django.db import models
from django.contrib.auth.models import User
from django.db.models import JSONField


class Location(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='locations')
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    latitude = models.FloatField()
    longitude = models.FloatField()
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
