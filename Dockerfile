FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .

RUN apt-get update && \
    apt-get install -y --no-install-recommends libaudit1 cron gettext && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Compile translation messages
RUN python manage.py compilemessages

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
    touch /var/log/cron.log

# Create startup script
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# Export environment variables to cron environment\n\
# Cron does not inherit environment variables from the container\n\
echo "Exporting environment variables to cron..."\n\
printenv | grep -E "^(SENTRY_|DJANGO_|LLM_)" | sed "s/^\\(.*\\)$/export \\1/g" > /etc/environment_vars.sh\n\
chmod +x /etc/environment_vars.sh\n\
\n\
# Update crontab to source environment variables before each command\n\
crontab -l > /tmp/current_cron\n\
sed -i "s|cd /app &&|cd /app \\&\\& . /etc/environment_vars.sh \\&\\&|g" /tmp/current_cron\n\
crontab /tmp/current_cron\n\
rm /tmp/current_cron\n\
\n\
# Start cron in the background\n\
echo "Starting cron..."\n\
cron\n\
\n\
# Start gunicorn in the foreground\n\
echo "Starting gunicorn..."\n\
exec gunicorn migraine_project.wsgi:application -c gunicorn.conf.py\n\
' > /app/start.sh && chmod +x /app/start.sh

# Expose port
EXPOSE 8889

# Start both cron and gunicorn
CMD ["/app/start.sh"]
