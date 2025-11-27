# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('forecast', '0018_weatherforecast_unique_location_target_time'),
    ]

    operations = [
        migrations.AddField(
            model_name='llmconfiguration',
            name='high_token_budget',
            field=models.BooleanField(
                default=False,
                help_text='Use high token budget for LLM prompts (more detailed weather context, hourly tables)'
            ),
        ),
    ]

