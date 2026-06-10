#!/bin/bash

echo '=== Task 1: Collecting Weather Data ==='
/usr/local/bin/python manage.py collect_weather_data
echo ''
echo '=== Task 2: Generating Predictions ==='
/usr/local/bin/python manage.py generate_predictions
echo ''
echo "=== All Tasks Completed at $(date '+%Y-%m-%d %H:%M:%S') ==="