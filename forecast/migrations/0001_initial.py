# Generated by Django 5.1.7 on 2025-03-31 13:25

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Location',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('city', models.CharField(max_length=100)),
                ('country', models.CharField(max_length=100)),
                ('latitude', models.FloatField()),
                ('longitude', models.FloatField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='locations', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ActualWeather',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('recorded_time', models.DateTimeField()),
                ('temperature', models.FloatField()),
                ('humidity', models.FloatField()),
                ('pressure', models.FloatField()),
                ('wind_speed', models.FloatField()),
                ('precipitation', models.FloatField()),
                ('cloud_cover', models.FloatField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('location', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='actual_weather', to='forecast.location')),
            ],
        ),
        migrations.CreateModel(
            name='WeatherForecast',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('forecast_time', models.DateTimeField()),
                ('target_time', models.DateTimeField()),
                ('temperature', models.FloatField()),
                ('humidity', models.FloatField()),
                ('pressure', models.FloatField()),
                ('wind_speed', models.FloatField()),
                ('precipitation', models.FloatField()),
                ('cloud_cover', models.FloatField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('location', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='forecasts', to='forecast.location')),
            ],
        ),
        migrations.CreateModel(
            name='WeatherComparisonReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('temperature_diff', models.FloatField()),
                ('humidity_diff', models.FloatField()),
                ('pressure_diff', models.FloatField()),
                ('wind_speed_diff', models.FloatField()),
                ('precipitation_diff', models.FloatField()),
                ('cloud_cover_diff', models.FloatField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actual', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='comparison_reports', to='forecast.actualweather')),
                ('location', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='comparison_reports', to='forecast.location')),
                ('forecast', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='comparison_reports', to='forecast.weatherforecast')),
            ],
        ),
        migrations.CreateModel(
            name='MigrainePrediction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('prediction_time', models.DateTimeField(auto_now_add=True)),
                ('target_time_start', models.DateTimeField()),
                ('target_time_end', models.DateTimeField()),
                ('probability', models.CharField(choices=[('LOW', 'Low'), ('MEDIUM', 'Medium'), ('HIGH', 'High')], max_length=10)),
                ('notification_sent', models.BooleanField(default=False)),
                ('location', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='predictions', to='forecast.location')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='predictions', to=settings.AUTH_USER_MODEL)),
                ('forecast', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='predictions', to='forecast.weatherforecast')),
            ],
        ),
    ]
