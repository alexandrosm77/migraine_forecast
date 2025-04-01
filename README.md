# Migraine Forecast Django Application

A Django application that predicts migraine probability based on weather forecast data for specified locations, sends email alerts for high probability, and compares forecasted data with actual data over time.

## Features

- Weather-based migraine prediction for the next 3-6 hours
- Email notifications for high migraine probability
- Location management for multiple tracking locations
- Comparison between forecasted and actual weather data
- User dashboard with prediction history and visualization
- SQLite database for data storage

## Installation

1. Clone the repository:
```
git clone https://github.com/yourusername/migraine-forecast.git
cd migraine-forecast
```

2. Create a virtual environment and activate it:
```
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```
pip install django requests
```

4. Apply migrations:
```
python manage.py migrate
```

5. Create a superuser (admin):
```
python manage.py createsuperuser
```

6. Run the development server:
```
python manage.py runserver
```

7. Access the application at http://127.0.0.1:8000/

## Configuration

### Email Settings

To enable email notifications, update the email settings in `migraine_project/email_settings.py`:

```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.yourmailserver.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-email@example.com'
EMAIL_HOST_PASSWORD = 'your-app-password'
DEFAULT_FROM_EMAIL = 'Migraine Forecast <your-email@example.com>'
```

For development/testing, the console backend is used by default when DEBUG=True.

## Usage

1. Register a new account or log in with an existing account
2. Add locations you want to monitor for migraine probability
3. View the dashboard to see recent predictions and high-risk alerts
4. Set up email notifications to receive alerts for high migraine probability
5. Check the comparison reports to see how accurate the weather forecasts have been

## Scheduled Tasks

For regular checks and notifications, set up a cron job or scheduled task to run:

```
python manage.py check_migraine_probability
```

This command will:
1. Fetch the latest weather forecasts for all locations
2. Generate migraine predictions
3. Send email notifications for high-risk predictions

Recommended schedule: Every 3 hours

## Weather Parameters

The application uses the following weather parameters for migraine prediction:

- Temperature changes
- Humidity levels (high and low)
- Barometric pressure changes
- Precipitation
- Cloud cover

## API Integration

The application uses the Open-Meteo Weather API (https://open-meteo.com/) to fetch weather forecast data. No API key is required for non-commercial use.

## Testing

Run the tests with:

```
python manage.py test forecast
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.



notes:
# Barometer

- docker login

- docker buildx build --platform linux/arm64/v8,linux/amd64 -t alexandrosm77/migraine_forecast --push .
