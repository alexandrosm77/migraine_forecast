from django.db.models import Max
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
import json

from .models import Location, WeatherForecast, ActualWeather, MigrainePrediction, WeatherComparisonReport
from .weather_service import WeatherService
from .prediction_service import MigrainePredictionService
from .comparison_service import DataComparisonService

# Initialize services
weather_service = WeatherService()
prediction_service = MigrainePredictionService()
comparison_service = DataComparisonService()

def index(request):
    """Home page view."""
    return render(request, 'forecast/index.html')

@login_required
def dashboard(request):
    """User dashboard view."""
    # Get user's locations
    locations = Location.objects.filter(user=request.user)
    
    # Get recent predictions
    recent_predictions = MigrainePrediction.objects.filter(
        user=request.user
    ).order_by('-prediction_time')[:5]
    
    # Check for high probability predictions in the next 24 hours
    now = timezone.now()
    upcoming_high_risk = MigrainePrediction.objects.filter(
        user=request.user,
        probability='HIGH',
        target_time_start__gte=now,
        target_time_start__lte=now + timedelta(hours=24)
    ).order_by('target_time_start')
    
    context = {
        'locations': locations,
        'recent_predictions': recent_predictions,
        'upcoming_high_risk': upcoming_high_risk,
    }
    
    return render(request, 'forecast/dashboard.html', context)

@login_required
def location_list(request):
    """View for listing user's locations."""
    locations = Location.objects.filter(user=request.user)
    
    context = {
        'locations': locations,
    }
    
    return render(request, 'forecast/location_list.html', context)

@login_required
def location_add(request):
    """View for adding a new location."""
    if request.method == 'POST':
        city = request.POST.get('city')
        country = request.POST.get('country')
        latitude = request.POST.get('latitude')
        longitude = request.POST.get('longitude')
        daily_limit = request.POST.get('daily_notification_limit')
        
        if city and country and latitude and longitude:
            try:
                # Validate and clamp daily limit
                try:
                    daily_limit_val = int(daily_limit) if daily_limit is not None and daily_limit != '' else 1
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
                
                messages.success(request, f'Location {city}, {country} added successfully!')
                return redirect('forecast:location_list')
            except Exception as e:
                messages.error(request, f'Error adding location: {str(e)}')
        else:
            messages.error(request, 'Please fill all required fields.')
    
    return render(request, 'forecast/location_add.html')

@login_required
def location_detail(request, location_id):
    """View for location details."""
    location = get_object_or_404(Location, id=location_id, user=request.user)

    # Handle updates to notification settings
    if request.method == 'POST':
        daily_limit = request.POST.get('daily_notification_limit')
        try:
            daily_limit_val = int(daily_limit) if daily_limit is not None and daily_limit != '' else location.daily_notification_limit
        except ValueError:
            daily_limit_val = location.daily_notification_limit
        if daily_limit_val < 0:
            daily_limit_val = 0
        if daily_limit_val != location.daily_notification_limit:
            location.daily_notification_limit = daily_limit_val
            location.save(update_fields=['daily_notification_limit'])
            messages.success(request, 'Notification settings updated.')
        else:
            messages.info(request, 'No changes to notification settings.')
        return redirect('forecast:location_detail', location_id=location.id)
    
    # Get recent forecasts

    # First, get the latest forecast_time for each target_time
    latest_forecasts = WeatherForecast.objects.filter(
        location=location
    ).values('target_time').annotate(
        latest_forecast_time=Max('forecast_time')
    )

    # Then, join this back to get the complete objects
    forecasts = WeatherForecast.objects.filter(
        location=location,
        forecast_time__in=[item['latest_forecast_time'] for item in latest_forecasts],
        target_time__in=[item['target_time'] for item in latest_forecasts]
    ).order_by('-forecast_time', 'target_time')[:24]

    # forecasts = WeatherForecast.objects.filter(
    #     location=location
    # ).order_by('-forecast_time', 'target_time')[:24]
    
    # Get recent predictions
    predictions = MigrainePrediction.objects.filter(
        location=location
    ).order_by('-prediction_time')[:5]

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
    
    # Get comparison data if available
    comparison_reports = WeatherComparisonReport.objects.filter(
        location=location,
        forecast__in=forecasts
    ).order_by('-created_at')[:10]
    
    context = {
        'location': location,
        'forecasts': forecasts,
        'predictions': predictions,
        'comparison_reports': comparison_reports,
        'sent_today': sent_today,
        'remaining_today': remaining_today,
    }
    
    return render(request, 'forecast/location_detail.html', context)

@login_required
def location_delete(request, location_id):
    """View for deleting a location."""
    location = get_object_or_404(Location, id=location_id, user=request.user)
    
    if request.method == 'POST':
        location.delete()
        messages.success(request, f'Location {location.city}, {location.country} deleted successfully!')
        return redirect('forecast:location_list')
    
    context = {
        'location': location,
    }
    
    return render(request, 'forecast/location_delete.html', context)

@login_required
def prediction_list(request):
    """View for listing migraine predictions."""
    predictions = MigrainePrediction.objects.filter(
        user=request.user
    ).order_by('-prediction_time')
    
    context = {
        'predictions': predictions,
    }
    
    return render(request, 'forecast/prediction_list.html', context)

@login_required
def prediction_detail(request, prediction_id):
    """View for prediction details."""
    prediction = get_object_or_404(MigrainePrediction, id=prediction_id, user=request.user)
    
    context = {
        'prediction': prediction,
    }
    
    return render(request, 'forecast/prediction_detail.html', context)

@login_required
def comparison_report(request):
    """View for comparison reports."""
    locations = Location.objects.filter(user=request.user)
    
    context = {
        'locations': locations,
    }
    
    return render(request, 'forecast/comparison_report.html', context)

@login_required
def comparison_detail(request, location_id):
    """View for detailed comparison data for a location."""
    location = get_object_or_404(Location, id=location_id, user=request.user)
    
    # Get comparison reports
    # First, get the latest forecast_time for each target_time
    latest_forecasts = WeatherForecast.objects.filter(
        location=location
    ).values('target_time').annotate(
        latest_forecast_time=Max('forecast_time')
    )

    # Then, join this back to get the complete objects
    forecasts = WeatherForecast.objects.filter(
        location=location,
        forecast_time__in=[item['latest_forecast_time'] for item in latest_forecasts],
        target_time__in=[item['target_time'] for item in latest_forecasts]
    ).order_by('-forecast_time', 'target_time')[:24]

    reports = WeatherComparisonReport.objects.filter(
        location=location,
        forecast__in=forecasts
    ).order_by('-created_at')[:30]
    
    # Get accuracy metrics
    metrics = comparison_service.get_forecast_accuracy_metrics(location)
    
    # Prepare data for charts
    chart_data = {
        'labels': [],
        'temperature_diff': [],
        'humidity_diff': [],
        'pressure_diff': [],
        'precipitation_diff': [],
        'cloud_cover_diff': []
    }
    
    for report in reports:
        chart_data['labels'].append(report.actual.recorded_time.strftime('%Y-%m-%d %H:%M'))
        chart_data['temperature_diff'].append(report.temperature_diff)
        chart_data['humidity_diff'].append(report.humidity_diff)
        chart_data['pressure_diff'].append(report.pressure_diff)
        chart_data['precipitation_diff'].append(report.precipitation_diff)
        chart_data['cloud_cover_diff'].append(report.cloud_cover_diff)
    
    context = {
        'location': location,
        'reports': reports,
        'metrics': metrics,
        'chart_data': json.dumps(chart_data),
    }
    
    return render(request, 'forecast/comparison_detail.html', context)

def register(request):
    """User registration view."""
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}! You can now log in.')
            return redirect('login')
    else:
        form = UserCreationForm()
    
    return render(request, 'forecast/register.html', {'form': form})

@login_required
def profile(request):
    """User profile view."""
    return render(request, 'forecast/profile.html')
