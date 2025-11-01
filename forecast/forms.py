from django import forms
from .models import UserHealthProfile


class UserHealthProfileForm(forms.ModelForm):
    class Meta:
        model = UserHealthProfile
        fields = [
            "age",
            "prior_conditions",
            "email_notifications_enabled",
            "daily_notification_limit",
            "notification_frequency_hours",
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
            "prior_conditions": forms.Textarea(
                attrs={"rows": 3, "placeholder": "e.g., aura, sinus issues, hypertension, etc."}
            ),
            "email_notifications_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
            "migraine_predictions_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
            "sinusitis_predictions_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }
        help_texts = {
            "sensitivity_overall": "0.5 = less sensitive, 1 = average, 2 = very sensitive",
        }

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

        return cleaned
