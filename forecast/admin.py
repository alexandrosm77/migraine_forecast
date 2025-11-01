from django.contrib import admin
from django_json_widget.widgets import JSONEditorWidget
from django.db.models import JSONField
from django.urls import path
from django.shortcuts import render
from django.http import StreamingHttpResponse
from forecast.models import (
    Location,
    WeatherForecast,
    MigrainePrediction,
    SinusitisPrediction,
    UserHealthProfile,
    LLMResponse,
    LLMConfiguration,
)
import subprocess
import time
import sys
from django.conf import settings
from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin, GroupAdmin


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("city", "country", "user", "latitude", "longitude", "created_at")
    search_fields = ("city", "country", "user__username")
    list_filter = ("country", "created_at", "user")

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
    search_fields = ("location__city", "location__country")
    list_filter = ("forecast_time", "target_time", "location")
    date_hierarchy = "forecast_time"

    def get_queryset(self, request):
        """Filter forecasts to show only those for the user's locations unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(location__user=request.user)


@admin.register(MigrainePrediction)
class MigrainePredictionAdmin(admin.ModelAdmin):
    list_display = ("user", "location", "probability", "prediction_time", "notification_sent")
    search_fields = ("user__username", "location__city")
    list_filter = ("probability", "notification_sent", "prediction_time")
    date_hierarchy = "prediction_time"
    formfield_overrides = {
        JSONField: {"widget": JSONEditorWidget(options={"mode": "text", "modes": ["text", "tree", "view"]})},
    }

    def get_queryset(self, request):
        """Filter predictions to show only the user's own predictions unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)


@admin.register(SinusitisPrediction)
class SinusitisPredictionAdmin(admin.ModelAdmin):
    list_display = ("user", "location", "probability", "prediction_time", "notification_sent")
    search_fields = ("user__username", "location__city")
    list_filter = ("probability", "notification_sent", "prediction_time")
    date_hierarchy = "prediction_time"
    formfield_overrides = {
        JSONField: {"widget": JSONEditorWidget(options={"mode": "text", "modes": ["text", "tree", "view"]})},
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
        "user",
        "age",
        "email_notifications_enabled",
        "daily_notification_limit",
        "migraine_predictions_enabled",
        "sinusitis_predictions_enabled",
        "sensitivity_overall",
        "sensitivity_temperature",
        "sensitivity_humidity",
        "sensitivity_pressure",
        "sensitivity_cloud_cover",
        "sensitivity_precipitation",
        "updated_at",
    )
    search_fields = ("user__username",)
    list_filter = ("email_notifications_enabled", "migraine_predictions_enabled", "sinusitis_predictions_enabled")

    def get_queryset(self, request):
        """Filter health profiles to show only the user's own profile unless they're a superuser."""
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
        "confidence",
    )
    list_filter = ("prediction_type", "probability_level", "created_at", "location")
    search_fields = ("location__city", "location__country", "user__username")
    readonly_fields = ("created_at",)
    formfield_overrides = {
        JSONField: {"widget": JSONEditorWidget(options={"mode": "text", "modes": ["text", "tree", "view"]})},
    }

    def get_prediction_link(self, obj):
        """Display a link to the associated prediction."""
        from django.urls import reverse
        from django.utils.html import format_html

        if obj.prediction_type == "migraine" and obj.migraine_prediction:
            url = reverse("admin:forecast_migraineprediction_change", args=[obj.migraine_prediction.id])
            return format_html('<a href="{}">Migraine #{}</a>', url, obj.migraine_prediction.id)
        elif obj.prediction_type == "sinusitis" and obj.sinusitis_prediction:
            url = reverse("admin:forecast_sinusitisprediction_change", args=[obj.sinusitis_prediction.id])
            return format_html('<a href="{}">Sinusitis #{}</a>', url, obj.sinusitis_prediction.id)
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

    list_display = ("name", "is_active", "model", "base_url", "timeout", "updated_at")
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
                "fields": ("base_url", "model", "api_key", "timeout"),
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
        urls = super().get_urls()
        custom_urls = [
            path("run-prediction-check/", self.admin_view(self.run_prediction_check_view), name="run_prediction_check"),
            path(
                "run-prediction-check/execute/",
                self.admin_view(self.execute_prediction_check),
                name="execute_prediction_check",
            ),
        ]
        return custom_urls + urls

    def index(self, request, extra_context=None):
        """Override index to add custom context."""
        extra_context = extra_context or {}
        extra_context["show_quick_actions"] = request.user.is_superuser
        return super().index(request, extra_context)

    def run_prediction_check_view(self, request):
        """View to display the prediction check form."""
        if not request.user.is_superuser:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Only superusers can access this page.")

        context = {
            **self.each_context(request),
            "title": "Run Prediction Check",
        }
        return render(request, "admin/run_prediction_check.html", context)

    def execute_prediction_check(self, request):
        """Execute the prediction check command and stream output."""
        if not request.user.is_superuser:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Only superusers can access this page.")

        # Get parameters from request
        test_notification = request.GET.get("test_notification", "")
        test_type = request.GET.get("test_type", "both")
        notify_only = request.GET.get("notify_only", "") == "on"

        def stream_output():
            """Generator function to stream command output."""
            # Build command
            cmd = [sys.executable, "manage.py", "check_migraine_probability"]

            if notify_only:
                cmd.append("--notify-only")

            if test_notification:
                cmd.extend(["--test-notification", test_notification])
                cmd.extend(["--test-type", test_type])

            # Yield initial HTML
            yield """<!DOCTYPE html>
<html>
<head>
    <title>Running Prediction Check</title>
    <style>
        body {
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            background-color: #1e1e1e;
            color: #d4d4d4;
            padding: 20px;
            margin: 0;
        }
        .header {
            background-color: #2d2d30;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            border-left: 4px solid #007acc;
        }
        .header h1 {
            margin: 0 0 10px 0;
            color: #007acc;
            font-size: 24px;
        }
        .command {
            background-color: #252526;
            padding: 10px;
            border-radius: 3px;
            font-size: 12px;
            color: #ce9178;
            margin-top: 10px;
        }
        .output {
            background-color: #1e1e1e;
            padding: 15px;
            border-radius: 5px;
            border: 1px solid #3e3e42;
            white-space: pre-wrap;
            font-size: 13px;
            line-height: 1.5;
        }
        .success { color: #4ec9b0; }
        .warning { color: #dcdcaa; }
        .error { color: #f48771; }
        .info { color: #9cdcfe; }
        .timestamp { color: #858585; }
        .back-link {
            display: inline-block;
            margin-top: 20px;
            padding: 10px 20px;
            background-color: #007acc;
            color: white;
            text-decoration: none;
            border-radius: 3px;
        }
        .back-link:hover {
            background-color: #005a9e;
        }
        .spinner {
            display: inline-block;
            width: 12px;
            height: 12px;
            border: 2px solid #3e3e42;
            border-top: 2px solid #007acc;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-right: 8px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .status {
            padding: 5px 10px;
            border-radius: 3px;
            display: inline-block;
            font-size: 12px;
            margin-left: 10px;
        }
        .status.running {
            background-color: #1a472a;
            color: #4ec9b0;
        }
        .status.complete {
            background-color: #1a472a;
            color: #4ec9b0;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1><span class="spinner"></span>Running Prediction Check <span class="status running">RUNNING</span></h1>
        <div class="command">Command: """ + " ".join(
                cmd
            ) + """</div>
    </div>
    <div class="output">"""

            # Run the command and stream output
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    bufsize=1,
                    cwd=settings.BASE_DIR,
                )

                for line in iter(process.stdout.readline, ""):
                    if line:
                        # Color code the output based on content
                        line_html = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

                        if "SUCCESS" in line or "✓" in line:
                            line_html = f'<span class="success">{line_html}</span>'
                        elif "WARNING" in line or "TEST MODE" in line:
                            line_html = f'<span class="warning">{line_html}</span>'
                        elif "ERROR" in line or "✗" in line or "Failed" in line:
                            line_html = f'<span class="error">{line_html}</span>'
                        elif "[" in line and "]" in line:
                            # Highlight timestamps
                            import re

                            line_html = re.sub(r"\[(.*?)\]", r'<span class="timestamp">[\1]</span>', line_html)

                        yield line_html
                        time.sleep(0.01)  # Small delay to ensure smooth streaming

                process.wait()

                if process.returncode == 0:
                    yield """</div>
    <div class="header" style="border-left-color: #4ec9b0; margin-top: 20px;">
        <h1 style="color: #4ec9b0;">✓ Command Completed Successfully <span class="status complete">COMPLETE</span></h1>
    </div>"""
                else:
                    yield f"""</div>
    <div class="header" style="border-left-color: #f48771; margin-top: 20px;">
        <h1 style="color: #f48771;">✗ Command Failed (Exit Code: {process.returncode})</h1>
    </div>"""

            except Exception as e:
                yield f"""<span class="error">Error executing command: {str(e)}</span></div>
    <div class="header" style="border-left-color: #f48771; margin-top: 20px;">
        <h1 style="color: #f48771;">✗ Execution Error</h1>
    </div>"""

            yield """
    <a href="/admin/run-prediction-check/" class="back-link">← Back to Prediction Check</a>
    <a href="/admin/" class="back-link">← Back to Admin Home</a>
    <script>
        // Auto-scroll to bottom
        window.scrollTo(0, document.body.scrollHeight);
        // Remove spinner when complete
        document.querySelector('.spinner').style.display = 'none';
    </script>
</body>
</html>"""

        return StreamingHttpResponse(stream_output(), content_type="text/html")


# Replace the default admin site
admin_site = MigraineAdminSite(name="admin")

# Re-register all models with the custom admin site
admin_site.register(Location, LocationAdmin)
admin_site.register(WeatherForecast, WeatherForecastAdmin)
admin_site.register(MigrainePrediction, MigrainePredictionAdmin)
admin_site.register(SinusitisPrediction, SinusitisPredictionAdmin)
admin_site.register(UserHealthProfile, UserHealthProfileAdmin)
admin_site.register(LLMResponse, LLMResponseAdmin)
admin_site.register(LLMConfiguration, LLMConfigurationAdmin)

# Register Django's default User and Group models
admin_site.register(User, UserAdmin)
admin_site.register(Group, GroupAdmin)
