from django import forms
from .models import UserHealthProfile


class UserHealthProfileForm(forms.ModelForm):
    class Meta:
        model = UserHealthProfile
        fields = [
            "language",
            "ui_version",
            "theme",
            "age",
            "prior_conditions",
            "email_notifications_enabled",
            "notification_mode",
            "digest_time",
            "notification_severity_threshold",
            "daily_notification_limit",
            "daily_migraine_notification_limit",
            "daily_sinusitis_notification_limit",
            "notification_frequency_hours",
            "quiet_hours_enabled",
            "quiet_hours_start",
            "quiet_hours_end",
            "prediction_window_start_hours",
            "prediction_window_end_hours",
            "migraine_predictions_enabled",
            "sinusitis_predictions_enabled",
            "sensitivity_overall",
            "sensitivity_temperature",
            "sensitivity_humidity",
            "sensitivity_pressure",
            "sensitivity_cloud_cover",
            "sensitivity_precipitation",
        ]
        widgets = {
            "language": forms.Select(
                attrs={
                    "class": "form-select block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",
                }
            ),
            "prior_conditions": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "e.g., aura, sinus issues, hypertension, etc.",
                    "class": "block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",
                }
            ),
            "email_notifications_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input h-4 w-4 text-teal-600 focus:ring-teal-500 border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700",
                }
            ),
            "quiet_hours_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input h-4 w-4 text-teal-600 focus:ring-teal-500 border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700",
                }
            ),
            "migraine_predictions_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input h-4 w-4 text-teal-600 focus:ring-teal-500 border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700",
                }
            ),
            "sinusitis_predictions_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input h-4 w-4 text-teal-600 focus:ring-teal-500 border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700",
                }
            ),
            "notification_mode": forms.Select(
                attrs={
                    "class": "form-select block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",
                }
            ),
            "notification_severity_threshold": forms.Select(
                attrs={
                    "class": "form-select block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",
                }
            ),
            "digest_time": forms.TimeInput(
                attrs={
                    "type": "time",
                    "class": "form-control block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",
                }
            ),
            "quiet_hours_start": forms.TimeInput(
                attrs={
                    "type": "time",
                    "class": "form-control block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",
                }
            ),
            "quiet_hours_end": forms.TimeInput(
                attrs={
                    "type": "time",
                    "class": "form-control block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",
                }
            ),
        }
        help_texts = {
            "sensitivity_overall": "0.5 = less sensitive, 1 = average, 2 = very sensitive",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add dark mode classes to all fields that don't have explicit widgets
        default_input_class = "block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
        default_select_class = "block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"

        for field_name, field in self.fields.items():
            if field_name not in self.Meta.widgets:
                if isinstance(field.widget, forms.Select):
                    field.widget.attrs['class'] = default_select_class
                elif isinstance(field.widget, (forms.NumberInput, forms.TextInput)):
                    field.widget.attrs['class'] = default_input_class

    def clean(self):
        cleaned = super().clean()

        # Clamp sensitivities to reasonable bounds
        for key in [
            "sensitivity_overall",
            "sensitivity_temperature",
            "sensitivity_humidity",
            "sensitivity_pressure",
            "sensitivity_cloud_cover",
            "sensitivity_precipitation",
        ]:
            val = cleaned.get(key)
            if val is None:
                continue
            # Allow 0.0 to 3.0
            if val < 0.0:
                cleaned[key] = 0.0
            elif val > 3.0:
                cleaned[key] = 3.0

        # Validate notification frequency (1-24 hours)
        notification_freq = cleaned.get("notification_frequency_hours")
        if notification_freq is not None:
            if notification_freq < 1:
                raise forms.ValidationError("Notification frequency must be at least 1 hour")
            elif notification_freq > 24:
                raise forms.ValidationError("Notification frequency cannot exceed 24 hours")

        # Validate prediction window
        window_start = cleaned.get("prediction_window_start_hours")
        window_end = cleaned.get("prediction_window_end_hours")

        if window_start is not None and window_start < 1:
            raise forms.ValidationError("Prediction window start must be at least 1 hour ahead")

        if window_end is not None and window_end > 72:
            raise forms.ValidationError("Prediction window end cannot exceed 72 hours ahead")

        if window_start is not None and window_end is not None:
            if window_start >= window_end:
                raise forms.ValidationError("Prediction window start must be before window end")
            if (window_end - window_start) < 1:
                raise forms.ValidationError("Prediction window must be at least 1 hour wide")

        # Validate quiet hours
        quiet_hours_enabled = cleaned.get("quiet_hours_enabled")
        quiet_hours_start = cleaned.get("quiet_hours_start")
        quiet_hours_end = cleaned.get("quiet_hours_end")

        if quiet_hours_enabled:
            if not quiet_hours_start or not quiet_hours_end:
                raise forms.ValidationError("Quiet hours start and end times are required when quiet hours are enabled")

        # Validate digest mode
        notification_mode = cleaned.get("notification_mode")
        digest_time = cleaned.get("digest_time")

        if notification_mode == "DIGEST":
            if not digest_time:
                raise forms.ValidationError("Digest time is required when using Daily Digest mode")

        # Validate per-type limits
        migraine_limit = cleaned.get("daily_migraine_notification_limit")
        sinusitis_limit = cleaned.get("daily_sinusitis_notification_limit")

        if migraine_limit is not None and migraine_limit < 0:
            raise forms.ValidationError("Migraine notification limit cannot be negative")

        if sinusitis_limit is not None and sinusitis_limit < 0:
            raise forms.ValidationError("Sinusitis notification limit cannot be negative")

        return cleaned
