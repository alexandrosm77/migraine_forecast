FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN apt-get update && \
    apt-get install -y --no-install-recommends libaudit1 && \
    rm -rf /var/lib/apt/lists/* \

RUN apt-get install -y --no-install-recommends cron supervisor && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Set up cron job for migraine probability check
RUN echo "0 */1 * * * cd /app && /usr/local/bin/python manage.py check_migraine_probability >> /var/log/cron.log 2>&1" > /etc/cron.d/migraine_check
RUN chmod 0644 /etc/cron.d/migraine_check && \
    crontab /etc/cron.d/migraine_check && \
    touch /var/log/cron.log && \
    chmod +x /app/start_django.sh && \
    echo "[supervisord]\nnodaemon=true\n\n[program:django]\ncommand=/app/start_django.sh\ndirectory=/app\nautorestart=true\nstdout_logfile=/dev/stdout\nstdout_logfile_maxbytes=0\nstderr_logfile=/dev/stderr\nstderr_logfile_maxbytes=0\n\n[program:cron]\ncommand=cron -f\nautorestart=true\nstdout_logfile=/dev/stdout\nstdout_logfile_maxbytes=0\nstderr_logfile=/dev/stderr\nstderr_logfile_maxbytes=0" > /etc/supervisor/conf.d/supervisord.conf

# Expose port
EXPOSE 8889

# Start supervisor (which will start both Django and cron)
CMD ["/usr/bin/supervisord"]
