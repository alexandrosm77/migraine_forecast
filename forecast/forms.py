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
            "quiet_hours_enabled",
            "quiet_hours_start",
            "quiet_hours_end",
            "migraine_predictions_enabled",
            "sinusitis_predictions_enabled",
            "sensitivity_preset",
        ]
        widgets = {
            "language": forms.Select(
                attrs={
                    "class": "form-select block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",  # noqa: E501
                }
            ),
            "prior_conditions": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "e.g., aura, sinus issues, hypertension, etc.",
                    "class": "block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",  # noqa: E501
                }
            ),
            "email_notifications_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input h-4 w-4 text-teal-600 focus:ring-teal-500 border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700",  # noqa: E501
                }
            ),
            "quiet_hours_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input h-4 w-4 text-teal-600 focus:ring-teal-500 border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700",  # noqa: E501
                }
            ),
            "migraine_predictions_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input h-4 w-4 text-teal-600 focus:ring-teal-500 border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700",  # noqa: E501
                }
            ),
            "sinusitis_predictions_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input h-4 w-4 text-teal-600 focus:ring-teal-500 border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700",  # noqa: E501
                }
            ),
            "notification_mode": forms.Select(
                attrs={
                    "class": "form-select block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",  # noqa: E501
                }
            ),
            "notification_severity_threshold": forms.Select(
                attrs={
                    "class": "form-select block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",  # noqa: E501
                }
            ),
            "digest_time": forms.TimeInput(
                attrs={
                    "type": "time",
                    "class": "form-control block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",  # noqa: E501
                }
            ),
            "quiet_hours_start": forms.TimeInput(
                attrs={
                    "type": "time",
                    "class": "form-control block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",  # noqa: E501
                }
            ),
            "quiet_hours_end": forms.TimeInput(
                attrs={
                    "type": "time",
                    "class": "form-control block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",  # noqa: E501
                }
            ),
            "sensitivity_preset": forms.Select(
                attrs={
                    "class": "form-select block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100",  # noqa: E501
                }
            ),
        }
        help_texts = {
            "quiet_hours_start": "Default: 22:00 (10 PM)",
            "quiet_hours_end": "Default: 07:00 (7 AM)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add dark mode classes to all fields that don't have explicit widgets
        default_input_class = "block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"  # noqa: E501
        default_select_class = "block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-teal-500 focus:border-teal-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"  # noqa: E501

        for field_name, field in self.fields.items():
            if field_name not in self.Meta.widgets:
                if isinstance(field.widget, forms.Select):
                    field.widget.attrs["class"] = default_select_class
                elif isinstance(field.widget, (forms.NumberInput, forms.TextInput)):
                    field.widget.attrs["class"] = default_input_class

    def clean(self):
        cleaned = super().clean()

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

        return cleaned
