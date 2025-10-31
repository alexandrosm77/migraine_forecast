from django.contrib import admin
from django_json_widget.widgets import JSONEditorWidget
from django.db.models import JSONField
from forecast.models import (
    Location,
    WeatherForecast,
    MigrainePrediction,
    UserHealthProfile,
    LLMResponse,
)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('city', 'country', 'user', 'latitude', 'longitude', 'created_at')
    search_fields = ('city', 'country', 'user__username')
    list_filter = ('country', 'created_at', 'user')

    def get_queryset(self, request):
        """Filter locations to show only the user's own locations unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)

    def save_model(self, request, obj, form, change):
        """Automatically set the user to the current user when creating a new location."""
        if not change:  # Only set user during creation
            obj.user = request.user
        super().save_model(request, obj, form, change)


@admin.register(WeatherForecast)
class WeatherForecastAdmin(admin.ModelAdmin):
    list_display = ('location', 'forecast_time', 'target_time', 'temperature', 'humidity', 'pressure')
    search_fields = ('location__city', 'location__country')
    list_filter = ('forecast_time', 'target_time', 'location')
    date_hierarchy = 'forecast_time'

    def get_queryset(self, request):
        """Filter forecasts to show only those for the user's locations unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(location__user=request.user)


@admin.register(MigrainePrediction)
class MigrainePredictionAdmin(admin.ModelAdmin):
    list_display = ('user', 'location', 'probability', 'prediction_time', 'notification_sent')
    search_fields = ('user__username', 'location__city')
    list_filter = ('probability', 'notification_sent', 'prediction_time')
    date_hierarchy = 'prediction_time'
    formfield_overrides = {
        JSONField: {'widget': JSONEditorWidget(options={'mode': 'text', 'modes': ['text', 'tree', 'view']})},
    }

    def get_queryset(self, request):
        """Filter predictions to show only the user's own predictions unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)


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

    def get_queryset(self, request):
        """Filter health profiles to show only the user's own profile unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)


@admin.register(LLMResponse)
class LLMResponseAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'user', 'location', 'prediction', 'probability_level', 'confidence'
    )
    list_filter = ('probability_level', 'created_at', 'location')
    search_fields = ('location__city', 'location__country', 'user__username')
    readonly_fields = ('created_at',)
    formfield_overrides = {
        JSONField: {'widget': JSONEditorWidget(options={'mode': 'text', 'modes': ['text', 'tree', 'view']})},
    }

    def get_queryset(self, request):
        """Filter LLM responses to show only the user's own responses unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)
