"""
Custom admin views for the prediction check workflow.

These are used by MigraineAdminSite and separated from admin.py to keep
the model-admin registrations readable.
"""
import logging
import os
import subprocess
import sys
import time

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import escape

logger = logging.getLogger(__name__)

_PREDICTION_COMMANDS = [
    "collect_weather_data",
    "generate_predictions",
    "process_notifications",
    "check_migraine_probability",
]


def _require_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Only superusers can access this page.")


def _log_file_path():
    return os.path.join(settings.BASE_DIR, "prediction_check.log")


def _script_file_path():
    return os.path.join(settings.BASE_DIR, "prediction_check_runner.sh")


def _is_process_running():
    """Check if a prediction-check process is still running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "prediction_check_runner.sh"],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            return True
        for cmd in _PREDICTION_COMMANDS:
            result = subprocess.run(
                ["pgrep", "-f", f"manage.py {cmd}"],
                capture_output=True, text=True,
            )
            if result.stdout.strip():
                return True
    except Exception:
        pass
    return False


# ------------------------------------------------------------------
# Views
# ------------------------------------------------------------------


def run_prediction_check_view(request, admin_site):
    """Display the prediction check form."""
    _require_superuser(request)
    context = {
        **admin_site.each_context(request),
        "title": "Run Prediction Check",
    }
    return render(request, "admin/run_prediction_check.html", context)


def execute_prediction_check(request):
    """Execute the prediction check command in background."""
    _require_superuser(request)

    test_notification = request.GET.get("test_notification", "")
    test_type = request.GET.get("test_type", "both")
    update_weather = request.GET.get("update_weather", "") == "on"
    get_predictions = request.GET.get("get_predictions", "") == "on"
    send_notifications = request.GET.get("send_notifications", "") == "on"

    log_file = _log_file_path()

    # Clear the log file
    try:
        with open(log_file, "w") as f:
            f.write(f"=== Prediction Check Started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
    except Exception:
        pass

    # Build shell script
    script_lines = ["#!/bin/bash", ""]

    if test_notification:
        script_lines.append(
            f"{sys.executable} manage.py check_migraine_probability "
            f"--test-notification {test_notification} --test-type {test_type}"
        )
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

    script_file = _script_file_path()
    try:
        with open(script_file, "w") as f:
            f.write("\n".join(script_lines))
        os.chmod(script_file, 0o755)
    except Exception as e:
        with open(log_file, "a") as f:
            f.write(f"Error creating script: {e}\n")
        return HttpResponseRedirect(reverse("admin:view_prediction_logs"))

    subprocess.Popen(
        ["/bin/bash", script_file],
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        cwd=settings.BASE_DIR,
        start_new_session=True,
    )


def view_prediction_logs(request):
    """Display prediction check logs with auto-refresh."""
    _require_superuser(request)

    log_file = _log_file_path()
    auto_refresh = request.GET.get("auto_refresh", "false") == "true"
    refresh_interval = int(request.GET.get("refresh_interval", "3"))
    message = request.GET.get("message", "")

    # Read log file
    log_content = ""
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                log_content = f.read()
                if not log_content:
                    log_content = "Log file is empty. Waiting for output..."
        except Exception as e:
            log_content = f"Error reading log file: {e}"
    else:
        log_content = "Log file not found. Start a prediction check to create it."

    process_running = _is_process_running()

    context = {
        "log_content": escape(log_content),
        "process_running": process_running,
        "auto_refresh": auto_refresh,
        "refresh_interval": refresh_interval,
        "message": message,
    }
    return render(request, "admin/prediction_logs.html", context)


def cancel_prediction_check(request):
    """Cancel running prediction check process."""
    _require_superuser(request)

    import signal

    log_file = _log_file_path()
    killed_count = 0
    pids_to_kill = set()

    try:
        result = subprocess.run(
            ["pgrep", "-f", "prediction_check_runner.sh"],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            pids_to_kill.update(result.stdout.strip().split("\n"))

        for cmd in _PREDICTION_COMMANDS:
            result = subprocess.run(
                ["pgrep", "-f", f"manage.py {cmd}"],
                capture_output=True, text=True,
            )
            if result.stdout.strip():
                pids_to_kill.update(result.stdout.strip().split("\n"))

        if pids_to_kill:
            for pid in pids_to_kill:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    killed_count += 1
                except (ProcessLookupError, Exception):
                    pass

            try:
                with open(log_file, "a") as f:
                    f.write(
                        f"\n\n=== Process Cancelled by {request.user.username} "
                        f"at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
                        f"Terminated {killed_count} process(es)\n"
                    )
            except Exception:
                pass

            message = f"Successfully cancelled prediction check ({killed_count} process(es) terminated)"
        else:
            message = "No running prediction check process found"
            try:
                with open(log_file, "a") as f:
                    f.write(
                        f"\n\n=== Cancel attempted but no process running "
                        f"at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
                    )
            except Exception:
                pass

    except Exception as e:
        message = f"Error cancelling process: {e}"
        try:
            with open(log_file, "a") as f:
                f.write(f"\n\n=== Error during cancellation: {e} ===\n")
        except Exception:
            pass

    return HttpResponseRedirect(reverse("admin:view_prediction_logs") + f"?message={message}")
