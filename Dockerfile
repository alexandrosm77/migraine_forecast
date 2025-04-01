FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install cron
RUN apt-get update && apt-get install -y cron supervisor && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Set up cron job for migraine probability check
RUN echo "0 */1 * * * cd /app && /usr/local/bin/python manage.py check_migraine_probability >> /var/log/cron.log 2>&1" > /etc/cron.d/migraine_check
RUN chmod 0644 /etc/cron.d/migraine_check
RUN crontab /etc/cron.d/migraine_check
RUN touch /var/log/cron.log

# Create supervisor configuration
RUN echo "[supervisord]\nnodaemon=true\n\n[program:django]\ncommand=python manage.py runserver 0.0.0.0:8889\ndirectory=/app\nautorestart=true\nstdout_logfile=/dev/stdout\nstdout_logfile_maxbytes=0\nstderr_logfile=/dev/stderr\nstderr_logfile_maxbytes=0\n\n[program:cron]\ncommand=cron -f\nautorestart=true\nstdout_logfile=/dev/stdout\nstdout_logfile_maxbytes=0\nstderr_logfile=/dev/stderr\nstderr_logfile_maxbytes=0" > /etc/supervisor/conf.d/supervisord.conf

# Run migrations
RUN python manage.py migrate

# Expose port
EXPOSE 8889

# Start supervisor (which will start both Django and cron)
CMD ["/usr/bin/supervisord"]
