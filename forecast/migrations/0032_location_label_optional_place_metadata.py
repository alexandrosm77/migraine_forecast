from django.db import migrations, models


def backfill_location_labels(apps, schema_editor):
    Location = apps.get_model("forecast", "Location")
    for location in Location.objects.all():
        if not location.label:
            location.label = location.city or f"{location.latitude:.4f}, {location.longitude:.4f}"
            location.save(update_fields=["label"])


class Migration(migrations.Migration):

    dependencies = [
        ("forecast", "0031_add_weatherforecast_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="location",
            name="label",
            field=models.CharField(default="", max_length=100),
        ),
        migrations.RunPython(backfill_location_labels, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="location",
            name="city",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AlterField(
            model_name="location",
            name="country",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]