from django.contrib import admin
from django_json_widget.widgets import JSONEditorWidget
from django.db.models import JSONField
from forecast.models import (
    Location,
    WeatherForecast,
    MigrainePrediction,
    SinusitisPrediction,
    UserHealthProfile,
    LLMResponse,
    LLMConfiguration,
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


@admin.register(SinusitisPrediction)
class SinusitisPredictionAdmin(admin.ModelAdmin):
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
        'email_notifications_enabled',
        'sensitivity_overall',
        'sensitivity_temperature',
        'sensitivity_humidity',
        'sensitivity_pressure',
        'sensitivity_cloud_cover',
        'sensitivity_precipitation',
        'updated_at',
    )
    search_fields = ('user__username',)
    list_filter = ('email_notifications_enabled',)

    def get_queryset(self, request):
        """Filter health profiles to show only the user's own profile unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)


@admin.register(LLMResponse)
class LLMResponseAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'user', 'location', 'prediction_type', 'get_prediction_link', 'probability_level', 'confidence'
    )
    list_filter = ('prediction_type', 'probability_level', 'created_at', 'location')
    search_fields = ('location__city', 'location__country', 'user__username')
    readonly_fields = ('created_at',)
    formfield_overrides = {
        JSONField: {'widget': JSONEditorWidget(options={'mode': 'text', 'modes': ['text', 'tree', 'view']})},
    }

    def get_prediction_link(self, obj):
        """Display a link to the associated prediction."""
        from django.urls import reverse
        from django.utils.html import format_html

        if obj.prediction_type == 'migraine' and obj.migraine_prediction:
            url = reverse('admin:forecast_migraineprediction_change', args=[obj.migraine_prediction.id])
            return format_html('<a href="{}">Migraine #{}</a>', url, obj.migraine_prediction.id)
        elif obj.prediction_type == 'sinusitis' and obj.sinusitis_prediction:
            url = reverse('admin:forecast_sinusitisprediction_change', args=[obj.sinusitis_prediction.id])
            return format_html('<a href="{}">Sinusitis #{}</a>', url, obj.sinusitis_prediction.id)
        return '-'
    get_prediction_link.short_description = 'Prediction'

    def get_queryset(self, request):
        """Filter LLM responses to show only the user's own responses unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)


@admin.register(LLMConfiguration)
class LLMConfigurationAdmin(admin.ModelAdmin):
    """
    Admin interface for LLM configuration.
    Only superusers can modify this.
    """
    list_display = ('enabled', 'model', 'base_url', 'timeout', 'updated_at')
    readonly_fields = ('updated_at',)
    fieldsets = (
        ('Status', {
            'fields': ('enabled',),
            'description': 'Enable or disable LLM predictions globally'
        }),
        ('API Configuration', {
            'fields': ('base_url', 'model', 'api_key', 'timeout'),
            'description': 'Configure the LLM API endpoint and model'
        }),
        ('Metadata', {
            'fields': ('updated_at',),
        }),
    )

    def has_add_permission(self, request):
        # Only allow one instance (singleton)
        return not LLMConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion of the singleton
        return False

    def get_queryset(self, request):
        """Only superusers can see/edit LLM configuration."""
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            return qs.none()
        return qs
