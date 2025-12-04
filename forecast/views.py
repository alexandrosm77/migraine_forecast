from django.db.models import Max
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.contrib import messages
from django.utils import timezone, translation
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.decorators.http import require_http_methods
from django.core.exceptions import PermissionDenied
from datetime import timedelta

from .models import Location, WeatherForecast, MigrainePrediction, SinusitisPrediction
from .weather_service import WeatherService
from .prediction_service import MigrainePredictionService
from .prediction_service_sinusitis import SinusitisPredictionService
from .notification_service import NotificationService
from .forms import UserHealthProfileForm

# Initialize services
weather_service = WeatherService()
prediction_service = MigrainePredictionService()
sinusitis_prediction_service = SinusitisPredictionService()


def get_template_name(request, base_name):
    """
    Get the appropriate template name based on user's UI version preference.

    Args:
        request: The HTTP request object
        base_name: The base template name (e.g., 'dashboard.html')

    Returns:
        The full template path (e.g., 'forecast/dashboard_v2.html' or 'forecast/dashboard.html')
    """
    ui_version = "v2"

    if request.user.is_authenticated:
        try:
            ui_version = request.user.health_profile.ui_version
        except Exception:
            pass

    if ui_version == "v2":
        name_without_ext = base_name.rsplit('.', 1)[0]
        ext = base_name.rsplit('.', 1)[1] if '.' in base_name else 'html'
        return f"forecast/{name_without_ext}_v2.{ext}"
    else:
        return f"forecast/{base_name}"


def index(request):
    """Home page view."""
    return render(request, get_template_name(request, "index.html"))


@login_required
def dashboard(request):
    """User dashboard view."""
    # Get user's locations
    locations = Location.objects.filter(user=request.user)

    # Get user preferences
    migraine_enabled = True
    sinusitis_enabled = True
    try:
        user_profile = request.user.health_profile
        migraine_enabled = user_profile.migraine_predictions_enabled
        sinusitis_enabled = user_profile.sinusitis_predictions_enabled
    except Exception:
        # If no health profile exists, default to both enabled
        pass

    # Get recent migraine predictions (only if enabled)
    recent_predictions = []
    upcoming_high_risk = []
    if migraine_enabled:
        recent_predictions = MigrainePrediction.objects.filter(user=request.user).order_by("-prediction_time")[:5]

        # Check for high probability predictions in the next 24 hours
        now = timezone.now()
        upcoming_high_risk = MigrainePrediction.objects.filter(
            user=request.user,
            probability="HIGH",
            target_time_start__gte=now,
            target_time_start__lte=now + timedelta(hours=24),
        ).order_by("target_time_start")

    # Get recent sinusitis predictions (only if enabled)
    recent_sinusitis_predictions = []
    upcoming_sinusitis_high_risk = []
    if sinusitis_enabled:
        recent_sinusitis_predictions = SinusitisPrediction.objects.filter(user=request.user).order_by(
            "-prediction_time"
        )[:5]

        # Check for high probability sinusitis predictions in the next 24 hours
        now = timezone.now()
        upcoming_sinusitis_high_risk = SinusitisPrediction.objects.filter(
            user=request.user,
            probability="HIGH",
            target_time_start__gte=now,
            target_time_start__lte=now + timedelta(hours=24),
        ).order_by("target_time_start")

    # Prepare high-risk predictions with analysis preview and weather trends
    high_risk_with_analysis = []
    for pred in upcoming_high_risk:
        wf = pred.weather_factors or {}
        analysis_text = wf.get("llm_analysis_text", "")
        # Truncate to ~150 characters for preview
        preview = analysis_text[:150] + "..." if len(analysis_text) > 150 else analysis_text

        # Get weather trends from weather_factors
        trends = []
        detailed_factors = wf.get("detailed_factors", {})
        if detailed_factors:
            for factor in detailed_factors.get("factors", []):
                trends.append({
                    "name": factor.get("name", ""),
                    "severity": factor.get("severity", ""),
                    "score": factor.get("score", 0),
                })

        high_risk_with_analysis.append({
            "prediction": pred,
            "analysis_preview": preview,
            "has_full_analysis": bool(analysis_text),
            "weather_trends": trends,
        })

    sinusitis_high_risk_with_analysis = []
    for pred in upcoming_sinusitis_high_risk:
        wf = pred.weather_factors or {}
        analysis_text = wf.get("llm_analysis_text", "")
        # Truncate to ~150 characters for preview
        preview = analysis_text[:150] + "..." if len(analysis_text) > 150 else analysis_text

        # Get weather trends from weather_factors
        trends = []
        detailed_factors = wf.get("detailed_factors", {})
        if detailed_factors:
            for factor in detailed_factors.get("factors", []):
                trends.append({
                    "name": factor.get("name", ""),
                    "severity": factor.get("severity", ""),
                    "score": factor.get("score", 0),
                })

        sinusitis_high_risk_with_analysis.append({
            "prediction": pred,
            "analysis_preview": preview,
            "has_full_analysis": bool(analysis_text),
            "weather_trends": trends,
        })

    # Get historical prediction data for charts (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)

    # Migraine prediction history
    migraine_history = []
    if migraine_enabled:
        historical_predictions = MigrainePrediction.objects.filter(
            user=request.user,
            prediction_time__gte=thirty_days_ago
        ).order_by('prediction_time')

        # Group by date and count by probability
        from collections import defaultdict
        daily_counts = defaultdict(lambda: {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0, 'date': None})

        for pred in historical_predictions:
            date_key = pred.prediction_time.date().isoformat()
            daily_counts[date_key]['date'] = pred.prediction_time.date().strftime('%b %d')
            daily_counts[date_key][pred.probability] += 1

        migraine_history = [
            {
                'date': data['date'],
                'high': data['HIGH'],
                'medium': data['MEDIUM'],
                'low': data['LOW'],
            }
            for date_key, data in sorted(daily_counts.items())
        ]

    # Sinusitis prediction history
    sinusitis_history = []
    if sinusitis_enabled:
        historical_sinusitis = SinusitisPrediction.objects.filter(
            user=request.user,
            prediction_time__gte=thirty_days_ago
        ).order_by('prediction_time')

        from collections import defaultdict
        daily_counts = defaultdict(lambda: {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0, 'date': None})

        for pred in historical_sinusitis:
            date_key = pred.prediction_time.date().isoformat()
            daily_counts[date_key]['date'] = pred.prediction_time.date().strftime('%b %d')
            daily_counts[date_key][pred.probability] += 1

        sinusitis_history = [
            {
                'date': data['date'],
                'high': data['HIGH'],
                'medium': data['MEDIUM'],
                'low': data['LOW'],
            }
            for date_key, data in sorted(daily_counts.items())
        ]

    # Convert history data to JSON for Chart.js
    import json
    migraine_history_json = json.dumps(migraine_history)
    sinusitis_history_json = json.dumps(sinusitis_history)

    # Get latest predictions for each location
    locations_with_predictions = []
    for location in locations:
        latest_migraine = None
        latest_sinusitis = None

        if migraine_enabled:
            latest_migraine = MigrainePrediction.objects.filter(
                user=request.user,
                location=location
            ).order_by('-prediction_time').first()

        if sinusitis_enabled:
            latest_sinusitis = SinusitisPrediction.objects.filter(
                user=request.user,
                location=location
            ).order_by('-prediction_time').first()

        locations_with_predictions.append({
            'location': location,
            'latest_migraine': latest_migraine,
            'latest_sinusitis': latest_sinusitis,
        })

    context = {
        "locations": locations,
        "locations_with_predictions": locations_with_predictions,
        "recent_predictions": recent_predictions,
        "recent_sinusitis_predictions": recent_sinusitis_predictions,
        "upcoming_high_risk": high_risk_with_analysis,
        "upcoming_sinusitis_high_risk": sinusitis_high_risk_with_analysis,
        "migraine_enabled": migraine_enabled,
        "sinusitis_enabled": sinusitis_enabled,
        "migraine_history": migraine_history_json,
        "sinusitis_history": sinusitis_history_json,
    }

    return render(request, get_template_name(request, "dashboard.html"), context)


@login_required
def location_list(request):
    """View for listing user's locations."""
    locations = Location.objects.filter(user=request.user)

    context = {
        "locations": locations,
    }

    return render(request, get_template_name(request, "location_list.html"), context)


@login_required
def location_add(request):
    """View for adding a new location."""
    if request.method == "POST":
        city = request.POST.get("city")
        country = request.POST.get("country")
        latitude = request.POST.get("latitude")
        longitude = request.POST.get("longitude")

        if city and country and latitude and longitude:
            try:
                location = Location.objects.create(
                    user=request.user,
                    city=city,
                    country=country,
                    latitude=float(latitude),
                    longitude=float(longitude),
                )

                # Fetch initial forecast for the new location (using upsert to prevent duplicates)
                weather_service.update_forecast_for_location_upsert(location)

                messages.success(request, f"Location {city}, {country} added successfully!")
                return redirect("forecast:location_list")
            except Exception as e:
                messages.error(request, f"Error adding location: {str(e)}")
        else:
            messages.error(request, "Please fill all required fields.")

    return render(request, get_template_name(request, "location_add.html"))


@login_required
def location_detail(request, location_id):
    """View for location details."""
    location = get_object_or_404(Location, id=location_id, user=request.user)

    # Get recent forecasts

    # First, get the latest forecast_time for each target_time
    latest_forecasts = (
        WeatherForecast.objects.filter(location=location)
        .values("target_time")
        .annotate(latest_forecast_time=Max("forecast_time"))
    )

    # Then, join this back to get the complete objects
    forecasts = WeatherForecast.objects.filter(
        location=location,
        forecast_time__in=[item["latest_forecast_time"] for item in latest_forecasts],
        target_time__in=[item["target_time"] for item in latest_forecasts],
    ).order_by("-forecast_time", "target_time")[:24]

    # forecasts = WeatherForecast.objects.filter(
    #     location=location
    # ).order_by('-forecast_time', 'target_time')[:24]

    # Get recent predictions
    predictions = MigrainePrediction.objects.filter(location=location).order_by("-prediction_time")[:5]

    context = {
        "location": location,
        "forecasts": forecasts,
        "predictions": predictions,
    }

    return render(request, get_template_name(request, "location_detail.html"), context)


@login_required
def location_edit(request, location_id):
    """View for editing a location."""
    location = get_object_or_404(Location, id=location_id, user=request.user)

    if request.method == "POST":
        city = request.POST.get("city")
        country = request.POST.get("country")
        latitude = request.POST.get("latitude")
        longitude = request.POST.get("longitude")
        timezone = request.POST.get("timezone")

        if city and country and latitude and longitude:
            try:
                location.city = city
                location.country = country
                location.latitude = float(latitude)
                location.longitude = float(longitude)
                if timezone:
                    location.timezone = timezone
                location.save()

                messages.success(request, f"Location {city}, {country} updated successfully!")
                return redirect("forecast:location_detail", location_id=location.id)
            except Exception as e:
                messages.error(request, f"Error updating location: {str(e)}")
        else:
            messages.error(request, "Please fill all required fields.")

    context = {
        "location": location,
    }

    return render(request, get_template_name(request, "location_edit.html"), context)


@login_required
def location_delete(request, location_id):
    """View for deleting a location."""
    location = get_object_or_404(Location, id=location_id, user=request.user)

    if request.method == "POST":
        location.delete()
        messages.success(request, f"Location {location.city}, {location.country} deleted successfully!")
        return redirect("forecast:location_list")

    context = {
        "location": location,
    }

    return render(request, get_template_name(request, "location_delete.html"), context)


@login_required
def prediction_list(request):
    """View for listing migraine predictions."""
    predictions_queryset = MigrainePrediction.objects.filter(user=request.user).order_by("-prediction_time")

    # Pagination - show 20 predictions per page
    paginator = Paginator(predictions_queryset, 20)
    page = request.GET.get("page", 1)

    try:
        predictions = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page
        predictions = paginator.page(1)
    except EmptyPage:
        # If page is out of range, deliver last page of results
        predictions = paginator.page(paginator.num_pages)

    context = {
        "predictions": predictions,
    }

    return render(request, get_template_name(request, "prediction_list.html"), context)


@login_required
def prediction_detail(request, prediction_id):
    """View for prediction details."""
    prediction = get_object_or_404(MigrainePrediction, id=prediction_id, user=request.user)

    # Build detailed factors similar to email, and expose LLM analysis/tips
    notif = NotificationService()
    try:
        detailed_factors = notif._get_detailed_weather_factors(prediction)
    except Exception:
        detailed_factors = {"factors": [], "total_score": 0, "contributing_factors_count": 0}
    wf = prediction.weather_factors or {}

    # Calculate human-readable weather factor values from forecasts
    from forecast.models import WeatherForecast
    import numpy as np

    weather_factor_values = {}
    try:
        forecasts = WeatherForecast.objects.filter(
            location=prediction.location,
            target_time__gte=prediction.target_time_start,
            target_time__lte=prediction.target_time_end,
        ).order_by("target_time")

        previous_forecasts = WeatherForecast.objects.filter(
            location=prediction.location, target_time__lt=prediction.target_time_start
        ).order_by("-target_time")[:6]

        if forecasts:
            temps = [f.temperature for f in forecasts]
            pressures = [f.pressure for f in forecasts]
            humidities = [f.humidity for f in forecasts]
            precipitations = [f.precipitation for f in forecasts]
            cloud_covers = [f.cloud_cover for f in forecasts]

            # Temperature range and change
            temp_min, temp_max = min(temps), max(temps)
            temp_range = temp_max - temp_min
            if previous_forecasts:
                prev_avg_temp = np.mean([f.temperature for f in previous_forecasts])
                avg_temp = np.mean(temps)
                temp_change = avg_temp - prev_avg_temp
                weather_factor_values["temperature_change"] = {
                    "change": f"{temp_change:+.1f}°C",
                    "range": f"{temp_min:.1f}°C to {temp_max:.1f}°C (range: {temp_range:.1f}°C)"
                }
            else:
                weather_factor_values["temperature_change"] = {
                    "change": "N/A",
                    "range": f"{temp_min:.1f}°C to {temp_max:.1f}°C (range: {temp_range:.1f}°C)"
                }

            # Pressure change and range
            pressure_min, pressure_max = min(pressures), max(pressures)
            pressure_range = pressure_max - pressure_min
            if previous_forecasts:
                prev_avg_pressure = np.mean([f.pressure for f in previous_forecasts])
                avg_pressure = np.mean(pressures)
                pressure_change = avg_pressure - prev_avg_pressure
                weather_factor_values["pressure_change"] = {
                    "change": f"{pressure_change:+.1f} hPa",
                    "range": f"{pressure_min:.1f} to {pressure_max:.1f} hPa (range: {pressure_range:.1f} hPa)"
                }
            else:
                weather_factor_values["pressure_change"] = {
                    "change": "N/A",
                    "range": f"{pressure_min:.1f} to {pressure_max:.1f} hPa (range: {pressure_range:.1f} hPa)"
                }

            # Humidity range and change
            humidity_min, humidity_max = min(humidities), max(humidities)
            humidity_range = humidity_max - humidity_min
            if previous_forecasts:
                prev_avg_humidity = np.mean([f.humidity for f in previous_forecasts])
                avg_humidity = np.mean(humidities)
                humidity_change = avg_humidity - prev_avg_humidity
                weather_factor_values["humidity_extreme"] = {
                    "change": f"{humidity_change:+.0f}%",
                    "range": f"{humidity_min:.0f}% to {humidity_max:.0f}% (range: {humidity_range:.0f}%)"
                }
            else:
                weather_factor_values["humidity_extreme"] = {
                    "change": "N/A",
                    "range": f"{humidity_min:.0f}% to {humidity_max:.0f}% (range: {humidity_range:.0f}%)"
                }

            # Precipitation
            total_precip = sum(precipitations)
            max_precip = max(precipitations)
            weather_factor_values["precipitation"] = {
                "total": f"{total_precip:.1f} mm",
                "max": f"{max_precip:.1f} mm/hour"
            }

            # Cloud cover range
            cloud_min, cloud_max = min(cloud_covers), max(cloud_covers)
            avg_cloud = np.mean(cloud_covers)
            weather_factor_values["cloud_cover"] = {
                "average": f"{avg_cloud:.0f}%",
                "range": f"{cloud_min:.0f}% to {cloud_max:.0f}%"
            }
    except Exception:
        pass

    context = {
        "prediction": prediction,
        "detailed_factors": detailed_factors,
        "llm_analysis_text": wf.get("llm_analysis_text"),
        "llm_rationale": wf.get("llm", {}).get("detail", {}).get("raw", {}).get("rationale"),
        "llm_prevention_tips": wf.get("llm_prevention_tips") or [],
        "weather_factor_values": weather_factor_values,
    }

    return render(request, get_template_name(request, "prediction_detail.html"), context)


@login_required
def sinusitis_prediction_list(request):
    """View for listing sinusitis predictions."""
    predictions_queryset = SinusitisPrediction.objects.filter(user=request.user).order_by("-prediction_time")

    # Pagination - show 20 predictions per page
    paginator = Paginator(predictions_queryset, 20)
    page = request.GET.get("page", 1)

    try:
        predictions = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page
        predictions = paginator.page(1)
    except EmptyPage:
        # If page is out of range, deliver last page of results
        predictions = paginator.page(paginator.num_pages)

    context = {
        "predictions": predictions,
    }

    return render(request, get_template_name(request, "sinusitis_prediction_list.html"), context)


@login_required
def sinusitis_prediction_detail(request, prediction_id):
    """View for sinusitis prediction details."""
    prediction = get_object_or_404(SinusitisPrediction, id=prediction_id, user=request.user)

    # Build detailed factors similar to email, and expose LLM analysis/tips
    notif = NotificationService()
    try:
        detailed_factors = notif._get_detailed_sinusitus_factors(prediction)
    except Exception:
        detailed_factors = {"factors": [], "total_score": 0, "contributing_factors_count": 0}
    wf = prediction.weather_factors or {}

    # Calculate human-readable weather factor values from forecasts
    from forecast.models import WeatherForecast
    import numpy as np

    weather_factor_values = {}
    try:
        forecasts = WeatherForecast.objects.filter(
            location=prediction.location,
            target_time__gte=prediction.target_time_start,
            target_time__lte=prediction.target_time_end,
        ).order_by("target_time")

        previous_forecasts = WeatherForecast.objects.filter(
            location=prediction.location, target_time__lt=prediction.target_time_start
        ).order_by("-target_time")[:6]

        if forecasts:
            temps = [f.temperature for f in forecasts]
            pressures = [f.pressure for f in forecasts]
            humidities = [f.humidity for f in forecasts]
            precipitations = [f.precipitation for f in forecasts]
            cloud_covers = [f.cloud_cover for f in forecasts]

            # Temperature range and change
            temp_min, temp_max = min(temps), max(temps)
            temp_range = temp_max - temp_min
            if previous_forecasts:
                prev_avg_temp = np.mean([f.temperature for f in previous_forecasts])
                avg_temp = np.mean(temps)
                temp_change = avg_temp - prev_avg_temp
                weather_factor_values["temperature_change"] = {
                    "change": f"{temp_change:+.1f}°C",
                    "range": f"{temp_min:.1f}°C to {temp_max:.1f}°C (range: {temp_range:.1f}°C)"
                }
            else:
                weather_factor_values["temperature_change"] = {
                    "change": "N/A",
                    "range": f"{temp_min:.1f}°C to {temp_max:.1f}°C (range: {temp_range:.1f}°C)"
                }

            # Pressure change and range
            pressure_min, pressure_max = min(pressures), max(pressures)
            pressure_range = pressure_max - pressure_min
            if previous_forecasts:
                prev_avg_pressure = np.mean([f.pressure for f in previous_forecasts])
                avg_pressure = np.mean(pressures)
                pressure_change = avg_pressure - prev_avg_pressure
                weather_factor_values["pressure_change"] = {
                    "change": f"{pressure_change:+.1f} hPa",
                    "range": f"{pressure_min:.1f} to {pressure_max:.1f} hPa (range: {pressure_range:.1f} hPa)"
                }
            else:
                weather_factor_values["pressure_change"] = {
                    "change": "N/A",
                    "range": f"{pressure_min:.1f} to {pressure_max:.1f} hPa (range: {pressure_range:.1f} hPa)"
                }

            # Humidity range and change
            humidity_min, humidity_max = min(humidities), max(humidities)
            humidity_range = humidity_max - humidity_min
            if previous_forecasts:
                prev_avg_humidity = np.mean([f.humidity for f in previous_forecasts])
                avg_humidity = np.mean(humidities)
                humidity_change = avg_humidity - prev_avg_humidity
                weather_factor_values["humidity_extreme"] = {
                    "change": f"{humidity_change:+.0f}%",
                    "range": f"{humidity_min:.0f}% to {humidity_max:.0f}% (range: {humidity_range:.0f}%)"
                }
            else:
                weather_factor_values["humidity_extreme"] = {
                    "change": "N/A",
                    "range": f"{humidity_min:.0f}% to {humidity_max:.0f}% (range: {humidity_range:.0f}%)"
                }

            # Precipitation
            total_precip = sum(precipitations)
            max_precip = max(precipitations)
            weather_factor_values["precipitation"] = {
                "total": f"{total_precip:.1f} mm",
                "max": f"{max_precip:.1f} mm/hour"
            }

            # Cloud cover range
            cloud_min, cloud_max = min(cloud_covers), max(cloud_covers)
            avg_cloud = np.mean(cloud_covers)
            weather_factor_values["cloud_cover"] = {
                "average": f"{avg_cloud:.0f}%",
                "range": f"{cloud_min:.0f}% to {cloud_max:.0f}%"
            }
    except Exception:
        pass

    context = {
        "prediction": prediction,
        "detailed_factors": detailed_factors,
        "llm_analysis_text": wf.get("llm_analysis_text"),
        "llm_rationale": wf.get("llm", {}).get("detail", {}).get("raw", {}).get("rationale"),
        "llm_prevention_tips": wf.get("llm_prevention_tips") or [],
        "weather_factor_values": weather_factor_values,
    }

    return render(request, get_template_name(request, "sinusitis_prediction_detail.html"), context)


def register(request):
    """User registration view."""
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get("username")
            messages.success(request, f"Account created for {username}! You can now log in.")
            return redirect("login")
    else:
        form = UserCreationForm()

    return render(request, get_template_name(request, "register.html"), {"form": form})


@login_required
def profile(request, user_id=None):
    """
    User profile view with health profile editing.
    Admins can view other users' profiles by passing user_id.
    """
    # Determine which user's profile to view
    if user_id and request.user.is_superuser:
        # Admin viewing another user's profile
        profile_user = get_object_or_404(User, id=user_id)
        is_viewing_other = True
    else:
        # User viewing their own profile
        profile_user = request.user
        is_viewing_other = False

    # Get or create the user's health profile
    try:
        profile = profile_user.health_profile
    except Exception:
        from .models import UserHealthProfile

        profile = None
        try:
            profile = UserHealthProfile.objects.get(user=profile_user)
        except UserHealthProfile.DoesNotExist:
            profile = UserHealthProfile(user=profile_user)

    if request.method == "POST" and not is_viewing_other:
        # Only allow editing own profile
        form = UserHealthProfileForm(request.POST, instance=profile)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = profile_user
            obj.save()
            messages.success(request, "Health profile updated successfully.")
            return redirect("forecast:profile")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = UserHealthProfileForm(instance=profile)

    # Provide locations info for template stats
    locations = Location.objects.filter(user=profile_user)

    context = {
        "form": form,
        "locations": locations,
        "profile_user": profile_user,
        "is_viewing_other": is_viewing_other,
    }
    return render(request, get_template_name(request, "profile.html"), context)


@login_required
@require_http_methods(["POST"])
def toggle_theme(request):
    """
    Toggle the user's theme preference between light and dark mode.
    """
    try:
        profile = request.user.health_profile
        # Toggle theme
        profile.theme = "dark" if profile.theme == "light" else "light"
        profile.save()
        messages.success(request, f"Theme switched to {profile.theme} mode")
    except Exception as e:
        messages.error(request, f"Failed to update theme: {str(e)}")

    # Redirect back to the previous page
    return redirect(request.META.get("HTTP_REFERER", "forecast:dashboard"))


@login_required
def set_language(request, language_code):
    """
    Set the user's preferred language and save it to their profile.
    """
    # Validate language code
    from django.conf import settings

    valid_languages = [lang[0] for lang in settings.LANGUAGES]
    if language_code not in valid_languages:
        messages.error(request, f"Invalid language code: {language_code}")
        return redirect(request.META.get("HTTP_REFERER", "forecast:index"))

    # Update user's language preference in their profile
    try:
        profile = request.user.health_profile
    except Exception:
        from .models import UserHealthProfile

        profile = None
        try:
            profile = UserHealthProfile.objects.get(user=request.user)
        except UserHealthProfile.DoesNotExist:
            profile = UserHealthProfile(user=request.user)

    profile.language = language_code
    profile.save()

    # Activate the language for the current session
    translation.activate(language_code)
    # Use Django's standard session key for language
    from django.conf import settings as django_settings

    request.session[django_settings.LANGUAGE_COOKIE_NAME] = language_code
    request.LANGUAGE_CODE = language_code

    messages.success(request, "Language preference updated successfully.")
    return redirect(request.META.get("HTTP_REFERER", "forecast:index"))


@login_required
def user_list(request):
    """
    View for listing all users in the system.
    Only accessible to superusers.
    """
    if not request.user.is_superuser:
        raise PermissionDenied("Only administrators can access this page.")

    users_queryset = User.objects.all().order_by("username")

    # Pagination - show 20 users per page
    paginator = Paginator(users_queryset, 20)
    page = request.GET.get("page", 1)

    try:
        users = paginator.page(page)
    except PageNotAnInteger:
        users = paginator.page(1)
    except EmptyPage:
        users = paginator.page(paginator.num_pages)

    context = {
        "users": users,
    }

    return render(request, get_template_name(request, "user_list.html"), context)


@login_required
def impersonate_user(request, user_id):
    """
    Start impersonating another user.
    Only accessible to superusers.
    Preserves the admin's original session.
    """
    if not request.user.is_superuser:
        raise PermissionDenied("Only administrators can impersonate users.")

    # Get the user to impersonate
    target_user = get_object_or_404(User, id=user_id)

    # Don't allow impersonating other superusers
    if target_user.is_superuser:
        messages.error(request, "You cannot impersonate other administrators.")
        return redirect("forecast:user_list")

    # Store the original user ID before logging in as the target user
    original_user_id = request.user.id

    # Log in as the target user
    login(request, target_user, backend="django.contrib.auth.backends.ModelBackend")

    # Store the original user ID in the session AFTER login
    # (login() cycles the session, so we need to set this after)
    request.session["impersonate_original_user_id"] = original_user_id
    request.session.modified = True

    messages.success(request, f"You are now impersonating {target_user.username}.")
    return redirect("forecast:dashboard")


@login_required
def stop_impersonation(request):
    """
    Stop impersonating and return to the original admin user.
    """
    original_user_id = request.session.get("impersonate_original_user_id")

    if not original_user_id:
        messages.error(request, "You are not currently impersonating anyone.")
        return redirect("forecast:dashboard")

    # Get the original user
    original_user = get_object_or_404(User, id=original_user_id)

    # Log back in as the original user
    login(request, original_user, backend="django.contrib.auth.backends.ModelBackend")

    # Remove the impersonation flag from session AFTER login
    # (to ensure it's removed from the new session)
    if "impersonate_original_user_id" in request.session:
        del request.session["impersonate_original_user_id"]
        request.session.modified = True

    messages.success(request, f"Stopped impersonating. You are now logged in as {original_user.username}.")
    return redirect("forecast:user_list")
