from django.contrib import admin
from forecast.models import (
    Location,
    WeatherForecast,
    MigrainePrediction,
    UserHealthProfile,
)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('city', 'country', 'user', 'latitude', 'longitude', 'created_at')
    search_fields = ('city', 'country', 'user__username')
    list_filter = ('country', 'created_at')


@admin.register(WeatherForecast)
class WeatherForecastAdmin(admin.ModelAdmin):
    list_display = ('location', 'forecast_time', 'target_time', 'temperature', 'humidity', 'pressure')
    search_fields = ('location__city', 'location__country')
    list_filter = ('forecast_time', 'target_time', 'location')
    date_hierarchy = 'forecast_time'


@admin.register(MigrainePrediction)
class MigrainePredictionAdmin(admin.ModelAdmin):
    list_display = ('user', 'location', 'probability', 'prediction_time', 'notification_sent')
    search_fields = ('user__username', 'location__city')
    list_filter = ('probability', 'notification_sent', 'prediction_time')
    date_hierarchy = 'prediction_time'


@admin.register(UserHealthProfile)
class UserHealthProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'age',
        'sensitivity_overall',
        'sensitivity_temperature',
        'sensitivity_humidity',
        'sensitivity_pressure',
        'sensitivity_cloud_cover',
        'sensitivity_precipitation',
        'updated_at',
    )
    search_fields = ('user__username',)
