# Generated by Django 5.1.7 on 2025-04-01 10:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('forecast', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='migraineprediction',
            name='weather_factors',
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
    ]
