# Kalliro Django Application

A Django application that predicts migraine, sinusitis, and hay fever risk based on weather forecast data for specified locations, sends email alerts for high-risk predictions, and compares forecasted data with actual data over time.

## Features

- Weather-based migraine, sinusitis, and hay fever prediction for the next 3-6 hours
- Email notifications for high health-risk predictions
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

To enable email notifications, update the email settings in `kalliro/email_settings.py`:

```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.yourmailserver.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-email@example.com'
EMAIL_HOST_PASSWORD = 'your-app-password'
DEFAULT_FROM_EMAIL = 'Kalliro <your-email@example.com>'
```

For development/testing, the console backend is used by default when DEBUG=True.

## Usage

1. Register a new account or log in with an existing account
2. Add locations you want to monitor for health-risk predictions
3. View the dashboard to see recent predictions and high-risk alerts
4. Set up email notifications to receive alerts for high health-risk predictions
5. Check the comparison reports to see how accurate the weather forecasts have been

## Scheduled Tasks

The application uses a **decoupled pipeline architecture** with three separate tasks that run independently:

### Task 1: Collect Weather Data
```bash
python manage.py collect_weather_data
```

This command:
- Fetches weather forecasts from the API for all locations
- Stores/updates forecast data in the database (using upsert to avoid duplicates)
- Cleans up old forecast data (older than 48 hours by default)

**Recommended schedule:** Every 2 hours
**Cron:** `0 */2 * * *`

### Task 2: Generate Predictions
```bash
python manage.py generate_predictions
```

This command:
- Reads existing weather forecasts from the database
- Generates migraine, sinusitis, and hay fever predictions (with optional LLM inference)
- Stores predictions in the database
- Cleans up old predictions (older than 7 days by default)

**Recommended schedule:** Every 2 hours (offset by 30 minutes)
**Cron:** `30 */2 * * *`

**Note:** This schedule is optimized for Raspberry Pi 5 with local LLM inference. Running every 2 hours instead of every 30 minutes reduces CPU load by 75% while still providing timely predictions.

### Task 3: Process Notifications
```bash
python manage.py process_notifications
```

This command:
- Finds recent HIGH/MEDIUM migraine, sinusitis, and hay fever predictions
- Builds a `NotificationIntake` send plan from the database
- Checks user preferences, quiet hours, severity threshold, daily limits, per-condition limits, frequency limits, and idempotency
- Sends one combined notification per user per run when eligible
- Records `NotificationLog` entries and marks prediction rows as sent after successful delivery

Useful options:
```bash
python manage.py process_notifications --dry-run
python manage.py process_notifications --replay
python manage.py process_notifications --override-limits
python manage.py process_notifications --lookback-hours 12
```

- `--dry-run` performs full discovery and verdict planning without creating logs, sending email, or marking predictions.
- `--replay` bypasses idempotency only; user preferences and rate limits still apply.
- `--override-limits` bypasses idempotency and rate limits, but still respects hard email safety checks.
- `--lookback-hours` overrides the default immediate notification lookback window.
- `--force` is still accepted as a deprecated alias for `--replay`.

**Recommended schedule:** Every 2 hours (offset by 1 hour from predictions)
**Cron:** `0 1-23/2 * * *`

### Daily Digest Notifications
```bash
python manage.py send_digest_notifications
```

This command keeps digest scheduling and digest-window prediction generation outside `NotificationIntake`. Once digest predictions exist, digest sending, notification verdicts, logging, and sent marking go through `NotificationIntake`.

Useful options:
```bash
python manage.py send_digest_notifications --force
python manage.py send_digest_notifications --user alice
```

### Alternative Schedules

The default 2-hour schedule is optimized for Raspberry Pi 5 with LLM inference. Here are alternative schedules for different use cases:

#### Conservative (Every 3 hours - 83% CPU reduction)
Best for battery/low power scenarios:
```bash
# Dockerfile cron jobs
0 */3 * * * collect_weather_data
0 1-23/3 * * * generate_predictions
0 2-23/3 * * * process_notifications
```

#### Peak Hours Only (6 AM - 10 PM - 81% CPU reduction)
Only run during waking hours:
```bash
# Dockerfile cron jobs
0 6-22/2 * * * collect_weather_data
30 6-22/2 * * * generate_predictions
0 7-23/2 * * * process_notifications
```

#### Morning/Evening (Twice daily - 96% CPU reduction)
Minimal CPU usage, daily planning only:
```bash
# Dockerfile cron jobs
0 7,19 * * * collect_weather_data
30 7,19 * * * generate_predictions
0 8,20 * * * process_notifications
```

To change the schedule, edit the `RUN echo` commands in the `Dockerfile` and rebuild the Docker image.

### Legacy Command (Deprecated)
The old monolithic command is still available but not recommended:
```bash
python manage.py check_migraine_probability
```

### Benefits of Decoupled Architecture
- **Independent failure:** If one task fails, others continue working
- **Flexible scheduling:** Each task can run at its optimal frequency
- **Better resource usage:** Weather data is fetched less frequently, predictions run more often
- **Easier debugging:** Each task has clear responsibilities and logs
- **No data duplication:** Forecasts are updated instead of duplicated

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
