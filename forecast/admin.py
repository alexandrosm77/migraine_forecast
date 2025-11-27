# flake8: noqa
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
    NotificationLog,
    LocationNotificationPreference,
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
        "language",
        "age",
        "email_notifications_enabled",
        "notification_mode",
        "notification_severity_threshold",
        "quiet_hours_enabled",
        "daily_notification_limit",
        "migraine_predictions_enabled",
        "sinusitis_predictions_enabled",
        "updated_at",
    )
    search_fields = ("user__username",)
    list_filter = (
        "language",
        "email_notifications_enabled",
        "notification_mode",
        "notification_severity_threshold",
        "quiet_hours_enabled",
        "migraine_predictions_enabled",
        "sinusitis_predictions_enabled",
    )
    fieldsets = (
        (
            "User Information",
            {
                "fields": ("user", "language", "age"),
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
                    "prediction_window_start_hours",
                    "prediction_window_end_hours",
                ),
            },
        ),
        (
            "Sensitivity Settings",
            {
                "fields": (
                    "sensitivity_overall",
                    "sensitivity_temperature",
                    "sensitivity_humidity",
                    "sensitivity_pressure",
                    "sensitivity_cloud_cover",
                    "sensitivity_precipitation",
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
                    "updated_at",
                ),
            },
        ),
    )
    readonly_fields = (
        "last_notification_sent_at",
        "last_migraine_notification_sent_at",
        "last_sinusitis_notification_sent_at",
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
    list_filter = (
        "notification_type",
        "channel",
        "status",
        "severity_level",
        "created_at",
        "sent_at",
    )
    search_fields = ("user__username", "subject", "error_message")
    readonly_fields = ("created_at", "sent_at")
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
                "fields": ("subject", "severity_level", "locations_count", "predictions_count"),
            },
        ),
        (
            "Related Predictions",
            {
                "fields": ("migraine_predictions", "sinusitis_predictions"),
            },
        ),
        (
            "Delivery Information",
            {
                "fields": ("sent_at", "error_message", "retry_count"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("metadata", "created_at"),
            },
        ),
    )

    formfield_overrides = {
        JSONField: {"widget": JSONEditorWidget(options={"mode": "text", "modes": ["text", "tree", "view"]})},
    }

    def get_queryset(self, request):
        """Filter notification logs to show only the user's own logs unless they're a superuser."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)


@admin.register(LocationNotificationPreference)
class LocationNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "location", "notifications_enabled", "priority")
    list_filter = ("notifications_enabled", "priority")
    search_fields = ("user__username", "location__city")

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
    )
    list_filter = ("prediction_type", "probability_level", "confidence_adjusted", "created_at", "location")
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
                "fields": ("base_url", "model", "api_key", "timeout", "high_token_budget", "confidence_threshold"),
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
            path(
                "run-prediction-check/logs/",
                self.admin_view(self.view_prediction_logs),
                name="view_prediction_logs",
            ),
            path(
                "run-prediction-check/cancel/",
                self.admin_view(self.cancel_prediction_check),
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
        """Execute the prediction check command in background."""
        if not request.user.is_superuser:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Only superusers can access this page.")

        import os
        from django.http import HttpResponseRedirect
        from django.urls import reverse

        # Get parameters from request
        test_notification = request.GET.get("test_notification", "")
        test_type = request.GET.get("test_type", "both")
        update_weather = request.GET.get("update_weather", "") == "on"
        get_predictions = request.GET.get("get_predictions", "") == "on"
        send_notifications = request.GET.get("send_notifications", "") == "on"

        # Build command
        log_file = os.path.join(settings.BASE_DIR, "prediction_check.log")

        # Clear the log file first
        try:
            with open(log_file, 'w') as f:
                f.write(f"=== Prediction Check Started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
        except Exception:
            pass

        # Create a shell script to run in background
        script_lines = ["#!/bin/bash", ""]

        if test_notification:
            script_lines.append(f"{sys.executable} manage.py check_migraine_probability --test-notification {test_notification} --test-type {test_type}")
        else:
            if update_weather:
                script_lines.append("echo '=== Task 1: Collecting Weather Data ==='")
                script_lines.append(f"{sys.executable} manage.py collect_weather_data")
                script_lines.append("echo ''")
            if get_predictions:
                script_lines.append("echo '=== Task 2: Generating Predictions ==='")
                script_lines.append(f"{sys.executable} manage.py generate_predictions")
                script_lines.append("echo ''")
            if send_notifications:
                script_lines.append("echo '=== Task 3: Processing Notifications ==='")
                script_lines.append(f"{sys.executable} manage.py process_notifications")
                script_lines.append("echo ''")
            if update_weather or get_predictions or send_notifications:
                script_lines.append("echo \"=== All Tasks Completed at $(date '+%Y-%m-%d %H:%M:%S') ===\"")
            else:
                script_lines.append("echo 'No tasks selected. Please select at least one pipeline step.'")
                script_lines.append("echo \"=== Completed at $(date '+%Y-%m-%d %H:%M:%S') ===\"")

        # Write script to temp file
        script_file = os.path.join(settings.BASE_DIR, "prediction_check_runner.sh")
        try:
            with open(script_file, 'w') as f:
                f.write('\n'.join(script_lines))
            os.chmod(script_file, 0o755)
        except Exception as e:
            # Fallback: write error to log
            with open(log_file, 'a') as f:
                f.write(f"Error creating script: {str(e)}\n")
            return HttpResponseRedirect(reverse('admin:view_prediction_logs'))

        # Execute script in background, redirecting output to log file
        subprocess.Popen(
            ['/bin/bash', script_file],
            stdout=open(log_file, 'a'),
            stderr=subprocess.STDOUT,
            cwd=settings.BASE_DIR,
            start_new_session=True  # Detach from parent process
        )

        # Redirect to log viewer with auto-refresh
        return HttpResponseRedirect(reverse('admin:view_prediction_logs') + '?auto_refresh=true')

    def view_prediction_logs(self, request):
        """View to display prediction check logs with auto-refresh."""
        if not request.user.is_superuser:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Only superusers can access this page.")

        import os
        from django.http import HttpResponse

        log_file = os.path.join(settings.BASE_DIR, "prediction_check.log")
        auto_refresh = request.GET.get("auto_refresh", "false") == "true"
        refresh_interval = int(request.GET.get("refresh_interval", "3"))  # seconds
        message = request.GET.get("message", "")

        # Read log file
        log_content = ""
        file_exists = os.path.exists(log_file)

        if file_exists:
            try:
                with open(log_file, "r") as f:
                    log_content = f.read()
                    if not log_content:
                        log_content = "Log file is empty. Waiting for output..."
            except Exception as e:
                log_content = f"Error reading log file: {str(e)}"
        else:
            log_content = "Log file not found. Start a prediction check to create it."

        # Check if process is still running
        process_running = False
        try:
            result = subprocess.run(
                ["pgrep", "-f", "manage.py (collect_weather_data|generate_predictions|process_notifications|check_migraine_probability)"],
                capture_output=True,
                text=True
            )
            process_running = bool(result.stdout.strip())
        except Exception:
            pass

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Prediction Check Logs</title>
    <meta charset="utf-8">
    {'<meta http-equiv="refresh" content="' + str(refresh_interval) + '">' if auto_refresh and process_running else ''}
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: #1e1e1e;
            color: #d4d4d4;
            padding: 20px;
            margin: 0;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        .header {{
            background-color: #2d2d30;
            padding: 20px;
            border-radius: 8px 8px 0 0;
            border-left: 4px solid #007acc;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 15px;
        }}
        h1 {{
            color: #4ec9b0;
            margin: 0;
            font-size: 24px;
        }}
        .controls {{
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }}
        .button {{
            background-color: #007acc;
            color: white;
            padding: 10px 20px;
            text-decoration: none;
            border-radius: 4px;
            border: none;
            cursor: pointer;
            font-size: 14px;
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }}
        .button:hover {{
            background-color: #005a9e;
        }}
        .button.secondary {{
            background-color: #3e3e42;
        }}
        .button.secondary:hover {{
            background-color: #505053;
        }}
        .button.success {{
            background-color: #28a745;
        }}
        .button.success:hover {{
            background-color: #218838;
        }}
        .status-badge {{
            padding: 5px 12px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
        }}
        .status-badge.running {{
            background-color: #28a745;
            color: white;
            animation: pulse 2s infinite;
        }}
        .status-badge.stopped {{
            background-color: #6c757d;
            color: white;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.6; }}
        }}
        .log-container {{
            background-color: #1e1e1e;
            border: 1px solid #3e3e42;
            border-radius: 0 0 8px 8px;
            padding: 20px;
            min-height: 400px;
            max-height: 800px;
            overflow-y: auto;
        }}
        .log-content {{
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 13px;
            line-height: 1.6;
            white-space: pre-wrap;
            word-wrap: break-word;
            color: #d4d4d4;
        }}
        .info-box {{
            background-color: #2d2d30;
            border-left: 4px solid #007acc;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 4px;
        }}
        .refresh-controls {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        select {{
            background-color: #3e3e42;
            color: #d4d4d4;
            border: 1px solid #555;
            padding: 8px 12px;
            border-radius: 4px;
            cursor: pointer;
        }}
        .spinner {{
            display: inline-block;
            width: 14px;
            height: 14px;
            border: 2px solid rgba(255,255,255,0.3);
            border-top-color: white;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }}
        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>📋 Prediction Check Logs</h1>
                <div style="margin-top: 5px;">
                    <span class="status-badge {'running' if process_running else 'stopped'}">
                        {'🟢 RUNNING' if process_running else '⚪ STOPPED'}
                    </span>
                </div>
            </div>
            <div class="controls">
                <div class="refresh-controls">
                    <label style="color: #d4d4d4; font-size: 14px;">
                        Auto-refresh:
                        <select id="refreshToggle" onchange="toggleRefresh()">
                            <option value="false" {'selected' if not auto_refresh else ''}>Off</option>
                            <option value="true" {'selected' if auto_refresh else ''}>On</option>
                        </select>
                    </label>
                    <label style="color: #d4d4d4; font-size: 14px;">
                        Interval:
                        <select id="refreshInterval" onchange="updateInterval()" {'disabled' if not auto_refresh else ''}>
                            <option value="2" {'selected' if refresh_interval == 2 else ''}>2s</option>
                            <option value="3" {'selected' if refresh_interval == 3 else ''}>3s</option>
                            <option value="5" {'selected' if refresh_interval == 5 else ''}>5s</option>
                            <option value="10" {'selected' if refresh_interval == 10 else ''}>10s</option>
                        </select>
                    </label>
                </div>
                <button class="button" onclick="window.location.reload()">
                    🔄 Refresh Now
                </button>
                {'<button class="button" style="background-color: #dc3545;" onclick="cancelProcess()">⏹ Cancel Process</button>' if process_running else ''}
                <a href="/admin/run-prediction-check/" class="button secondary">
                    ← Back
                </a>
            </div>
        </div>

        {f'''<div style="background-color: #28a745; color: white; padding: 15px; margin: 20px 0; border-radius: 4px; border-left: 4px solid #1e7e34;">
            <strong>✓ {message}</strong>
        </div>''' if message else ''}

        <div class="log-container">
            <div class="log-content">{log_content if log_content else 'No logs available yet.'}</div>
        </div>
    </div>

    <script>
        // Auto-scroll to bottom immediately and on load
        function scrollToBottom() {{
            const logContainer = document.querySelector('.log-container');
            if (logContainer) {{
                logContainer.scrollTop = logContainer.scrollHeight;
            }}
            // Also scroll window to bottom
            window.scrollTo(0, document.body.scrollHeight);
        }}

        // Scroll immediately (before page fully loads)
        scrollToBottom();

        // Scroll again after page fully loads (in case content loaded late)
        window.addEventListener('load', scrollToBottom);

        // Scroll after a short delay to catch any late-loading content
        setTimeout(scrollToBottom, 100);

        function toggleRefresh() {{
            const enabled = document.getElementById('refreshToggle').value;
            const interval = document.getElementById('refreshInterval').value;
            const url = new URL(window.location);
            url.searchParams.set('auto_refresh', enabled);
            url.searchParams.set('refresh_interval', interval);
            window.location.href = url.toString();
        }}

        function updateInterval() {{
            const interval = document.getElementById('refreshInterval').value;
            const url = new URL(window.location);
            url.searchParams.set('refresh_interval', interval);
            window.location.href = url.toString();
        }}

        function cancelProcess() {{
            if (confirm('Are you sure you want to cancel the running prediction check?\\n\\nThis will terminate all running tasks.')) {{
                window.location.href = '/admin/run-prediction-check/cancel/';
            }}
        }}
    </script>
</body>
</html>"""

        return HttpResponse(html)

    def cancel_prediction_check(self, request):
        """Cancel running prediction check process."""
        if not request.user.is_superuser:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Only superusers can access this page.")

        import os
        import signal
        from django.http import HttpResponse, HttpResponseRedirect
        from django.urls import reverse

        log_file = os.path.join(settings.BASE_DIR, "prediction_check.log")

        # Find and kill the running processes
        killed_count = 0
        try:
            # Find processes running the management commands
            result = subprocess.run(
                ["pgrep", "-f", "manage.py (collect_weather_data|generate_predictions|process_notifications|check_migraine_probability)"],
                capture_output=True,
                text=True
            )

            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGTERM)  # Graceful termination
                        killed_count += 1
                    except ProcessLookupError:
                        pass  # Process already finished
                    except Exception as e:
                        pass  # Ignore other errors

                # Also kill the bash script runner if it exists
                result = subprocess.run(
                    ["pgrep", "-f", "prediction_check_runner.sh"],
                    capture_output=True,
                    text=True
                )
                if result.stdout.strip():
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        try:
                            os.kill(int(pid), signal.SIGTERM)
                            killed_count += 1
                        except:
                            pass

                # Log the cancellation
                try:
                    with open(log_file, 'a') as f:
                        f.write(f"\n\n=== Process Cancelled by {request.user.username} at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                        f.write(f"Terminated {killed_count} process(es)\n")
                except Exception:
                    pass

                message = f"Successfully cancelled prediction check ({killed_count} process(es) terminated)"
            else:
                message = "No running prediction check process found"
                try:
                    with open(log_file, 'a') as f:
                        f.write(f"\n\n=== Cancel attempted but no process running at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                except Exception:
                    pass

        except Exception as e:
            message = f"Error cancelling process: {str(e)}"
            try:
                with open(log_file, 'a') as f:
                    f.write(f"\n\n=== Error during cancellation: {str(e)} ===\n")
            except Exception:
                pass

        # Redirect back to logs with message
        return HttpResponseRedirect(reverse('admin:view_prediction_logs') + f'?message={message}')


# Replace the default admin site
admin_site = MigraineAdminSite(name="admin")

# Re-register all models with the custom admin site
admin_site.register(Location, LocationAdmin)
admin_site.register(WeatherForecast, WeatherForecastAdmin)
admin_site.register(MigrainePrediction, MigrainePredictionAdmin)
admin_site.register(SinusitisPrediction, SinusitisPredictionAdmin)
admin_site.register(UserHealthProfile, UserHealthProfileAdmin)
admin_site.register(NotificationLog, NotificationLogAdmin)
admin_site.register(LocationNotificationPreference, LocationNotificationPreferenceAdmin)
admin_site.register(LLMResponse, LLMResponseAdmin)
admin_site.register(LLMConfiguration, LLMConfigurationAdmin)

# Register Django's default User and Group models
admin_site.register(User, UserAdmin)
admin_site.register(Group, GroupAdmin)
