#!/bin/bash

echo '=== Task 1: Collecting Weather Data ==='
/Users/alexandros/.pyenv/versions/migraine/bin/python manage.py collect_weather_data
echo ''
echo '=== Task 2: Generating Predictions ==='
/Users/alexandros/.pyenv/versions/migraine/bin/python manage.py generate_predictions
echo ''
echo "=== All Tasks Completed at $(date '+%Y-%m-%d %H:%M:%S') ==="