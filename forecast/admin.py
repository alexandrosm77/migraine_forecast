# flake8: noqa
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.models import User, Group
from django.db.models import JSONField
from django.urls import path
from django_json_widget.widgets import JSONEditorWidget

from forecast.models import (
    Location,
    WeatherForecast,
    MigrainePrediction,
    SinusitisPrediction,
    HayFeverPrediction,
    AirQualityForecast,
    UserHealthProfile,
    LLMResponse,
    LLMConfiguration,
    NotificationLog,
    LocationNotificationPreference,
)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("city", "country", "user", "latitude", "longitude", "timezone", "created_at")
    list_select_related = ("user",)
    search_fields = ("city", "country", "user__username")
    list_filter = ("country", "created_at", "user")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            None,
            {
                "fields": ("user", "city", "country", "latitude", "longitude", "timezone"),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

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
    list_display = ("location", "forecast_time", "target_time", "temperature", "humidity", "pressure")
    list_select_related = ("location",)
    show_full_result_count = False
    search_fields = ("location__city", "location__country")
    list_filter = ("forecast_time", "target_time", "location")
    date_hierarchy = "forecast_time"
    readonly_fields = ("created_at",)
    fieldsets = (
        (
            None,
            {
                "fields": ("location", "forecast_time", "target_time"),
            },
        ),
        (
            "Weather Data",
            {
                "fields": ("temperature", "humidity", "pressure", "wind_speed", "precipitation", "cloud_cover"),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at",),
            },
        ),
    )

    def get_queryset(self, request):
        """Filter forecasts to show only those for the user's locations unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(location__user=request.user)


class BasePredictionAdmin(admin.ModelAdmin):
    """Shared configuration for MigrainePrediction, SinusitisPrediction, and HayFeverPrediction."""

    list_display = ("user", "location", "probability", "prediction_time", "target_time_start", "target_time_end", "notification_sent")
    list_select_related = ("user", "location")
    show_full_result_count = False
    search_fields = ("user__username", "location__city")
    list_filter = ("probability", "notification_sent", "prediction_time")
    date_hierarchy = "prediction_time"
    readonly_fields = ("prediction_time",)
    formfield_overrides = {
        JSONField: {"widget": JSONEditorWidget(options={"mode": "text", "modes": ["text", "tree", "view"]})},
    }
    fieldsets = (
        (
            None,
            {
                "fields": ("user", "location", "forecast", "probability", "notification_sent"),
            },
        ),
        (
            "Time Window",
            {
                "fields": ("prediction_time", "target_time_start", "target_time_end"),
            },
        ),
        (
            "Weather Factors",
            {
                "fields": ("weather_factors",),
            },
        ),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)


@admin.register(MigrainePrediction)
class MigrainePredictionAdmin(BasePredictionAdmin):
    raw_id_fields = ("user", "location", "forecast")


@admin.register(SinusitisPrediction)
class SinusitisPredictionAdmin(BasePredictionAdmin):
    raw_id_fields = ("user", "location", "forecast")


@admin.register(HayFeverPrediction)
class HayFeverPredictionAdmin(BasePredictionAdmin):
    raw_id_fields = ("user", "location", "forecast", "air_quality_forecast")
    fieldsets = (
        (
            None,
            {
                "fields": ("user", "location", "forecast", "air_quality_forecast", "probability", "notification_sent"),
            },
        ),
        (
            "Time Window",
            {
                "fields": ("prediction_time", "target_time_start", "target_time_end"),
            },
        ),
        (
            "Weather Factors",
            {
                "fields": ("weather_factors",),
            },
        ),
    )


@admin.register(AirQualityForecast)
class AirQualityForecastAdmin(admin.ModelAdmin):
    list_display = ("location", "forecast_time", "target_time", "european_aqi", "us_aqi", "pm2_5", "pm10", "grass_pollen", "uv_index")
    list_select_related = ("location",)
    show_full_result_count = False
    raw_id_fields = ("location",)
    search_fields = ("location__city", "location__country")
    list_filter = ("forecast_time", "target_time", "location")
    date_hierarchy = "forecast_time"
    readonly_fields = ("created_at",)
    fieldsets = (
        (
            None,
            {
                "fields": ("location", "forecast_time", "target_time"),
            },
        ),
        (
            "Pollen (grains/m³)",
            {
                "fields": ("alder_pollen", "birch_pollen", "grass_pollen", "mugwort_pollen", "olive_pollen", "ragweed_pollen"),
            },
        ),
        (
            "Air Quality",
            {
                "fields": ("pm10", "pm2_5", "ozone", "nitrogen_dioxide", "dust", "uv_index", "european_aqi", "us_aqi"),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at",),
            },
        ),
    )

    def get_queryset(self, request):
        """Filter air-quality rows to show only those for the user's locations unless superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(location__user=request.user)


@admin.register(UserHealthProfile)
class UserHealthProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "language",
        "sensitivity_preset",
        "age",
        "email_notifications_enabled",
        "notification_mode",
        "notification_severity_threshold",
        "quiet_hours_enabled",
        "daily_notification_limit",
        "migraine_predictions_enabled",
        "sinusitis_predictions_enabled",
        "hay_fever_predictions_enabled",
        "updated_at",
    )
    list_select_related = ("user",)
    search_fields = ("user__username",)
    list_filter = (
        "language",
        "sensitivity_preset",
        "email_notifications_enabled",
        "notification_mode",
        "notification_severity_threshold",
        "quiet_hours_enabled",
        "migraine_predictions_enabled",
        "sinusitis_predictions_enabled",
        "hay_fever_predictions_enabled",
    )
    fieldsets = (
        (
            "User Information",
            {
                "fields": ("user", "language", "age", "prior_conditions", "sensitivity_preset"),
            },
        ),
        (
            "UI Preferences",
            {
                "fields": ("ui_version", "theme"),
            },
        ),
        (
            "Notification Settings",
            {
                "fields": (
                    "email_notifications_enabled",
                    "notification_mode",
                    "digest_time",
                    "notification_severity_threshold",
                    "notification_frequency_hours",
                ),
            },
        ),
        (
            "Notification Limits",
            {
                "fields": (
                    "daily_notification_limit",
                    "daily_migraine_notification_limit",
                    "daily_sinusitis_notification_limit",
                    "daily_hay_fever_notification_limit",
                ),
            },
        ),
        (
            "Quiet Hours",
            {
                "fields": (
                    "quiet_hours_enabled",
                    "quiet_hours_start",
                    "quiet_hours_end",
                ),
            },
        ),
        (
            "Prediction Settings",
            {
                "fields": (
                    "migraine_predictions_enabled",
                    "sinusitis_predictions_enabled",
                    "hay_fever_predictions_enabled",
                    "prediction_window_start_hours",
                    "prediction_window_end_hours",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "last_notification_sent_at",
                    "last_migraine_notification_sent_at",
                    "last_sinusitis_notification_sent_at",
                    "last_hay_fever_notification_sent_at",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )
    readonly_fields = (
        "last_notification_sent_at",
        "last_migraine_notification_sent_at",
        "last_sinusitis_notification_sent_at",
        "last_hay_fever_notification_sent_at",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request):
        """Filter health profiles to show only the user's own profile unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "notification_type",
        "channel",
        "status",
        "severity_level",
        "locations_count",
        "predictions_count",
        "sent_at",
        "created_at",
    )
    list_select_related = ("user",)
    show_full_result_count = False
    list_filter = (
        "notification_type",
        "channel",
        "status",
        "severity_level",
        "created_at",
        "sent_at",
    )
    search_fields = ("user__username", "subject", "recipient", "error_message")
    readonly_fields = ("created_at", "updated_at", "sent_at", "migraine_predictions_links", "sinusitis_predictions_links", "hayfever_predictions_links")
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Basic Information",
            {
                "fields": ("user", "notification_type", "channel", "status"),
            },
        ),
        (
            "Content",
            {
                "fields": ("subject", "recipient", "severity_level", "locations_count", "predictions_count"),
            },
        ),
        (
            "Related Predictions",
            {
                "fields": ("migraine_predictions_links", "sinusitis_predictions_links", "hayfever_predictions_links"),
            },
        ),
        (
            "Delivery Information",
            {
                "fields": ("scheduled_time", "sent_at", "error_message", "retry_count"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("metadata", "created_at", "updated_at"),
            },
        ),
    )

    formfield_overrides = {
        JSONField: {"widget": JSONEditorWidget(options={"mode": "text", "modes": ["text", "tree", "view"]})},
    }

    def _build_prediction_links(self, queryset, url_name):
        """Build clickable links for a set of related predictions."""
        from django.urls import reverse
        from django.utils.html import format_html, format_html_join

        predictions = queryset.all()
        if not predictions:
            return "-"
        return format_html_join(
            ", ",
            '<a href="{}">{} ({})</a>',
            (
                (
                    reverse(url_name, args=[p.pk]),
                    f"#{p.pk}",
                    p.probability,
                )
                for p in predictions
            ),
        )

    def migraine_predictions_links(self, obj):
        return self._build_prediction_links(obj.migraine_predictions, "admin:forecast_migraineprediction_change")

    migraine_predictions_links.short_description = "Migraine Predictions"

    def sinusitis_predictions_links(self, obj):
        return self._build_prediction_links(obj.sinusitis_predictions, "admin:forecast_sinusitisprediction_change")

    sinusitis_predictions_links.short_description = "Sinusitis Predictions"

    def hayfever_predictions_links(self, obj):
        return self._build_prediction_links(obj.hayfever_predictions, "admin:forecast_hayfeverprediction_change")

    hayfever_predictions_links.short_description = "Hay Fever Predictions"

    def get_queryset(self, request):
        """Filter notification logs to show only the user's own logs unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)


@admin.register(LocationNotificationPreference)
class LocationNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "location", "notifications_enabled", "priority", "created_at")
    list_select_related = ("user", "location")
    list_filter = ("notifications_enabled", "priority")
    search_fields = ("user__username", "location__city")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            None,
            {
                "fields": ("user", "location", "notifications_enabled", "priority"),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    def get_queryset(self, request):
        """Filter location preferences to show only the user's own preferences unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)


@admin.register(LLMResponse)
class LLMResponseAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "user",
        "location",
        "prediction_type",
        "get_prediction_link",
        "probability_level",
        "original_probability_level",
        "confidence",
        "confidence_adjusted",
        "inference_time",
    )
    list_select_related = ("user", "location", "migraine_prediction", "sinusitis_prediction", "hayfever_prediction")
    show_full_result_count = False
    list_filter = ("prediction_type", "probability_level", "confidence_adjusted", "created_at", "location")
    search_fields = ("location__city", "location__country", "user__username")
    readonly_fields = ("created_at",)
    raw_id_fields = ("user", "location", "migraine_prediction", "sinusitis_prediction", "hayfever_prediction")
    formfield_overrides = {
        JSONField: {"widget": JSONEditorWidget(options={"mode": "text", "modes": ["text", "tree", "view"]})},
    }
    fieldsets = (
        (
            "Associations",
            {
                "fields": ("user", "location", "prediction_type", "migraine_prediction", "sinusitis_prediction", "hayfever_prediction"),
            },
        ),
        (
            "Classification",
            {
                "fields": ("probability_level", "original_probability_level", "confidence", "confidence_adjusted"),
            },
        ),
        (
            "LLM Output",
            {
                "fields": ("rationale", "analysis_text", "prevention_tips", "inference_time"),
            },
        ),
        (
            "Raw Data",
            {
                "classes": ("collapse",),
                "fields": ("request_payload", "response_api_raw", "response_parsed"),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at",),
            },
        ),
    )

    def get_prediction_link(self, obj):
        """Display a link to the associated prediction."""
        from django.urls import reverse
        from django.utils.html import format_html

        if obj.prediction_type == "migraine" and obj.migraine_prediction_id:
            url = reverse("admin:forecast_migraineprediction_change", args=[obj.migraine_prediction_id])
            return format_html('<a href="{}">Migraine #{}</a>', url, obj.migraine_prediction_id)
        elif obj.prediction_type == "sinusitis" and obj.sinusitis_prediction_id:
            url = reverse("admin:forecast_sinusitisprediction_change", args=[obj.sinusitis_prediction_id])
            return format_html('<a href="{}">Sinusitis #{}</a>', url, obj.sinusitis_prediction_id)
        elif obj.prediction_type == "hayfever" and obj.hayfever_prediction_id:
            url = reverse("admin:forecast_hayfeverprediction_change", args=[obj.hayfever_prediction_id])
            return format_html('<a href="{}">Hay Fever #{}</a>', url, obj.hayfever_prediction_id)
        return "-"

    get_prediction_link.short_description = "Prediction"

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
    Supports multiple configurations with only one active at a time.
    """

    list_display = ("name", "is_active", "model", "base_url", "timeout", "confidence_threshold", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "model", "base_url")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Identification",
            {
                "fields": ("name", "is_active"),
                "description": "Name this configuration and set it as active (only one can be active at a time)",
            },
        ),
        (
            "API Configuration",
            {
                "fields": ("base_url", "model", "api_key", "timeout", "high_token_budget", "confidence_threshold", "extra_payload"),
                "description": "Configure the LLM API endpoint and model",
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    def get_queryset(self, request):
        """Only superusers can see/edit LLM configuration."""
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            return qs.none()
        return qs

    def has_module_permission(self, request):
        """Only superusers can access this module."""
        return request.user.is_superuser


# Custom Admin Site with additional views
class MigraineAdminSite(admin.AdminSite):
    site_header = "Migraine Forecast Administration"
    site_title = "Migraine Forecast Admin"
    index_title = "Welcome to Migraine Forecast Administration"
    index_template = "admin/custom_index.html"

    def get_urls(self):
        from . import admin_views

        urls = super().get_urls()
        custom_urls = [
            path("run-prediction-check/", self.admin_view(self.run_prediction_check_view), name="run_prediction_check"),
            path(
                "run-prediction-check/execute/",
                self.admin_view(admin_views.execute_prediction_check),
                name="execute_prediction_check",
            ),
            path(
                "run-prediction-check/logs/",
                self.admin_view(admin_views.view_prediction_logs),
                name="view_prediction_logs",
            ),
            path(
                "run-prediction-check/cancel/",
                self.admin_view(admin_views.cancel_prediction_check),
                name="cancel_prediction_check",
            ),
        ]
        return custom_urls + urls

    def index(self, request, extra_context=None):
        """Override index to add custom context."""
        extra_context = extra_context or {}
        extra_context["show_quick_actions"] = request.user.is_superuser
        return super().index(request, extra_context)

    def run_prediction_check_view(self, request):
        from . import admin_views
        return admin_views.run_prediction_check_view(request, self)



# Replace the default admin site
admin_site = MigraineAdminSite(name="admin")

# Re-register all models with the custom admin site
admin_site.register(Location, LocationAdmin)
admin_site.register(WeatherForecast, WeatherForecastAdmin)
admin_site.register(MigrainePrediction, MigrainePredictionAdmin)
admin_site.register(SinusitisPrediction, SinusitisPredictionAdmin)
admin_site.register(HayFeverPrediction, HayFeverPredictionAdmin)
admin_site.register(AirQualityForecast, AirQualityForecastAdmin)
admin_site.register(UserHealthProfile, UserHealthProfileAdmin)
admin_site.register(NotificationLog, NotificationLogAdmin)
admin_site.register(LocationNotificationPreference, LocationNotificationPreferenceAdmin)
admin_site.register(LLMResponse, LLMResponseAdmin)
admin_site.register(LLMConfiguration, LLMConfigurationAdmin)

# Register Django's default User and Group models
admin_site.register(User, UserAdmin)
admin_site.register(Group, GroupAdmin)
