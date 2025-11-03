FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .

RUN apt-get update && \
    apt-get install -y --no-install-recommends libaudit1 cron supervisor && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

# Set up cron jobs for decoupled pipeline architecture (Optimized for Raspberry Pi 5)
# Task 1: Collect weather data every 2 hours
# Task 2: Generate predictions every 2 hours (offset by 30 min)
# Task 3: Process notifications every 2 hours (offset by 1 hour)
# Task 4: Send digest notifications every hour (to catch different user digest times)
# This reduces CPU load by 75% compared to 30-minute intervals, important for LLM inference on Pi
RUN echo "0 */2 * * * cd /app && /usr/local/bin/python manage.py collect_weather_data >> /var/log/cron.log 2>&1" > /etc/cron.d/migraine_pipeline && \
    echo "30 */2 * * * cd /app && /usr/local/bin/python manage.py generate_predictions >> /var/log/cron.log 2>&1" >> /etc/cron.d/migraine_pipeline && \
    echo "0 1-23/2 * * * cd /app && /usr/local/bin/python manage.py process_notifications >> /var/log/cron.log 2>&1" >> /etc/cron.d/migraine_pipeline && \
    echo "0 * * * * cd /app && /usr/local/bin/python manage.py send_digest_notifications >> /var/log/cron.log 2>&1" >> /etc/cron.d/migraine_pipeline
RUN chmod 0644 /etc/cron.d/migraine_pipeline && \
    crontab /etc/cron.d/migraine_pipeline && \
    touch /var/log/cron.log && \
    echo "[supervisord]\nnodaemon=true\n\n[program:django]\ncommand=/bin/bash -c 'python manage.py migrate && gunicorn migraine_project.wsgi:application -c gunicorn.conf.py'\ndirectory=/app\nautorestart=true\nstdout_logfile=/dev/stdout\nstdout_logfile_maxbytes=0\nstderr_logfile=/dev/stderr\nstderr_logfile_maxbytes=0\n\n[program:cron]\ncommand=cron -f\nautorestart=true\nstdout_logfile=/dev/stdout\nstdout_logfile_maxbytes=0\nstderr_logfile=/dev/stderr\nstderr_logfile_maxbytes=0" > /etc/supervisor/conf.d/supervisord.conf

# Expose port
EXPOSE 8889

# Start supervisor (which will start both Django and cron)
CMD ["/usr/bin/supervisord"]
