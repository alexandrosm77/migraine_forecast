from django.db.models import Max
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
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


def index(request):
    """Home page view."""
    return render(request, "forecast/index.html")


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

    context = {
        "locations": locations,
        "recent_predictions": recent_predictions,
        "recent_sinusitis_predictions": recent_sinusitis_predictions,
        "upcoming_high_risk": upcoming_high_risk,
        "upcoming_sinusitis_high_risk": upcoming_sinusitis_high_risk,
        "migraine_enabled": migraine_enabled,
        "sinusitis_enabled": sinusitis_enabled,
    }

    return render(request, "forecast/dashboard.html", context)


@login_required
def location_list(request):
    """View for listing user's locations."""
    locations = Location.objects.filter(user=request.user)

    context = {
        "locations": locations,
    }

    return render(request, "forecast/location_list.html", context)


@login_required
def location_add(request):
    """View for adding a new location."""
    if request.method == "POST":
        city = request.POST.get("city")
        country = request.POST.get("country")
        latitude = request.POST.get("latitude")
        longitude = request.POST.get("longitude")
        daily_limit = request.POST.get("daily_notification_limit")

        if city and country and latitude and longitude:
            try:
                # Validate and clamp daily limit
                try:
                    daily_limit_val = int(daily_limit) if daily_limit is not None and daily_limit != "" else 1
                except ValueError:
                    daily_limit_val = 1
                if daily_limit_val < 0:
                    daily_limit_val = 0

                location = Location.objects.create(
                    user=request.user,
                    city=city,
                    country=country,
                    latitude=float(latitude),
                    longitude=float(longitude),
                    daily_notification_limit=daily_limit_val,
                )

                # Fetch initial forecast for the new location
                weather_service.update_forecast_for_location(location)

                messages.success(request, f"Location {city}, {country} added successfully!")
                return redirect("forecast:location_list")
            except Exception as e:
                messages.error(request, f"Error adding location: {str(e)}")
        else:
            messages.error(request, "Please fill all required fields.")

    return render(request, "forecast/location_add.html")


@login_required
def location_detail(request, location_id):
    """View for location details."""
    location = get_object_or_404(Location, id=location_id, user=request.user)

    # Handle updates to notification settings
    if request.method == "POST":
        daily_limit = request.POST.get("daily_notification_limit")
        try:
            daily_limit_val = (
                int(daily_limit) if daily_limit is not None and daily_limit != "" else location.daily_notification_limit
            )
        except ValueError:
            daily_limit_val = location.daily_notification_limit
        if daily_limit_val < 0:
            daily_limit_val = 0
        if daily_limit_val != location.daily_notification_limit:
            location.daily_notification_limit = daily_limit_val
            location.save(update_fields=["daily_notification_limit"])
            messages.success(request, "Notification settings updated.")
        else:
            messages.info(request, "No changes to notification settings.")
        return redirect("forecast:location_detail", location_id=location.id)

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

    # Compute today's notification usage for this location
    from django.utils import timezone as dj_timezone

    now = dj_timezone.now()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    sent_today = MigrainePrediction.objects.filter(
        user=request.user,
        location=location,
        notification_sent=True,
        prediction_time__gte=start_of_day,
        prediction_time__lt=end_of_day,
    ).count()
    remaining_today = max(location.daily_notification_limit - sent_today, 0)

    context = {
        "location": location,
        "forecasts": forecasts,
        "predictions": predictions,
        "sent_today": sent_today,
        "remaining_today": remaining_today,
    }

    return render(request, "forecast/location_detail.html", context)


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

    return render(request, "forecast/location_delete.html", context)


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

    return render(request, "forecast/prediction_list.html", context)


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

    context = {
        "prediction": prediction,
        "detailed_factors": detailed_factors,
        "llm_analysis_text": wf.get("llm_analysis_text"),
        "llm_prevention_tips": wf.get("llm_prevention_tips") or [],
    }

    return render(request, "forecast/prediction_detail.html", context)


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

    return render(request, "forecast/sinusitis_prediction_list.html", context)


@login_required
def sinusitis_prediction_detail(request, prediction_id):
    """View for sinusitis prediction details."""
    prediction = get_object_or_404(SinusitisPrediction, id=prediction_id, user=request.user)

    # Build detailed factors similar to email, and expose LLM analysis/tips
    notif = NotificationService()
    try:
        detailed_factors = notif._get_detailed_sinusitis_factors(prediction)
    except Exception:
        detailed_factors = {"factors": [], "total_score": 0, "contributing_factors_count": 0}
    wf = prediction.weather_factors or {}

    context = {
        "prediction": prediction,
        "detailed_factors": detailed_factors,
        "llm_analysis_text": wf.get("llm_analysis_text"),
        "llm_prevention_tips": wf.get("llm_prevention_tips") or [],
    }

    return render(request, "forecast/sinusitis_prediction_detail.html", context)


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

    return render(request, "forecast/register.html", {"form": form})


@login_required
def profile(request):
    """User profile view with health profile editing."""
    # Get or create the user's health profile
    try:
        profile = request.user.health_profile
    except Exception:
        from .models import UserHealthProfile

        profile = None
        try:
            profile = UserHealthProfile.objects.get(user=request.user)
        except UserHealthProfile.DoesNotExist:
            profile = UserHealthProfile(user=request.user)

    if request.method == "POST":
        form = UserHealthProfileForm(request.POST, instance=profile)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            obj.save()
            messages.success(request, "Health profile updated successfully.")
            return redirect("forecast:profile")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = UserHealthProfileForm(instance=profile)

    # Provide locations info for template stats
    locations = Location.objects.filter(user=request.user)

    context = {
        "form": form,
        "locations": locations,
    }
    return render(request, "forecast/profile.html", context)
