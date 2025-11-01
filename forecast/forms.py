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
        return cleaned
