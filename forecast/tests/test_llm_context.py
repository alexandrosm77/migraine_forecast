from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

from forecast.models import Location, WeatherForecast


class LLMContextBuilderTest(TestCase):
    """Test cases for LLMContextBuilder"""

    def setUp(self):
        from forecast.llm_context_builder import LLMContextBuilder

        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")
        self.location = Location.objects.create(
            user=self.user, city="London", country="UK", latitude=51.5074, longitude=-0.1278
        )
        # Create forecasts for testing
        now = timezone.now()
        self.forecasts = []
        for i in range(6):
            forecast = WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=now + timedelta(hours=3 + i),
                temperature=15.0 + i * 0.5,
                humidity=70 + i,
                pressure=1013.0 - i * 0.5,
                precipitation=0.0,
                cloud_cover=50,
                wind_speed=10.0,
            )
            self.forecasts.append(forecast)

        # Create previous forecasts
        self.previous_forecasts = []
        for i in range(6):
            forecast = WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now - timedelta(hours=6),
                target_time=now - timedelta(hours=6 - i),
                temperature=12.0 + i * 0.3,
                humidity=65 + i,
                pressure=1018.0 - i * 0.3,
                precipitation=0.0,
                cloud_cover=40,
                wind_speed=8.0,
            )
            self.previous_forecasts.append(forecast)

        self.builder_low = LLMContextBuilder(high_token_budget=False)
        self.builder_high = LLMContextBuilder(high_token_budget=True)

    def test_build_migraine_context_low_token(self):
        """Test building migraine context with low token budget"""
        context = self.builder_low.build_context(
            "migraine",
            forecasts=self.forecasts,
            previous_forecasts=self.previous_forecasts,
            location=self.location,
        )
        # Should contain location
        self.assertIn("London", context)
        self.assertIn("UK", context)
        # Should contain weather data
        self.assertIn("Temp", context)
        self.assertIn("Pressure", context)
        # Should NOT contain hourly table (low token)
        self.assertNotIn("Hour", context)

    def test_build_migraine_context_high_token(self):
        """Test building migraine context with high token budget"""
        context = self.builder_high.build_context(
            "migraine",
            forecasts=self.forecasts,
            previous_forecasts=self.previous_forecasts,
            location=self.location,
        )
        # Should contain location
        self.assertIn("London", context)
        # Should contain hourly table (high token)
        self.assertIn("Time", context)  # Header changed from "Hour" to "Time"
        self.assertIn("Temp", context)
        self.assertIn("Press", context)

    def test_build_sinusitis_context_includes_seasonal_info(self):
        """Test that sinusitis context includes seasonal health information"""
        context = self.builder_low.build_context(
            "sinusitis",
            forecasts=self.forecasts,
            previous_forecasts=self.previous_forecasts,
            location=self.location,
        )
        # Should contain location
        self.assertIn("London", context)
        # Should contain seasonal health context (pollen, mold, heating)
        # At least one of these should be present
        has_seasonal = any(
            term in context.lower() for term in ["pollen", "mold", "heating", "humidity", "season"]
        )
        self.assertTrue(has_seasonal)

    def test_user_sensitivity_translation(self):
        """Test that user sensitivity preset is translated to natural language"""
        user_profile = {
            "sensitivity_preset": "HIGH",
        }
        context = self.builder_low.build_context(
            "migraine",
            forecasts=self.forecasts,
            previous_forecasts=self.previous_forecasts,
            location=self.location,
            user_profile=user_profile,
        )
        # Should contain sensitivity information in natural language
        self.assertIn("sensitivity", context.lower())
        self.assertIn("high", context.lower())

    def test_weather_changes_calculation(self):
        """Test that weather changes are calculated correctly"""
        context = self.builder_low.build_context(
            "migraine",
            forecasts=self.forecasts,
            previous_forecasts=self.previous_forecasts,
            location=self.location,
        )
        # Should contain change information
        # The context should show temperature and pressure changes
        self.assertIn("°C", context)
        self.assertIn("hPa", context)

    def test_diurnal_context_for_latitude(self):
        """Test that diurnal context is appropriate for latitude"""
        # London is at ~51.5° latitude (mid-latitude)
        context = self.builder_high.build_context(
            "migraine",
            forecasts=self.forecasts,
            previous_forecasts=self.previous_forecasts,
            location=self.location,
        )
        # Should contain some reference to normal temperature variation
        # This is included in the high token budget version
        self.assertIn("London", context)

    def test_weather_comparison_formatting(self):
        """Test that weather comparison (past 24h vs forecast) is formatted correctly"""
        context = self.builder_low.build_context(
            "migraine",
            forecasts=self.forecasts,
            previous_forecasts=self.previous_forecasts,
            location=self.location,
        )
        # Should contain weather comparison information
        self.assertIn("Past", context)
        self.assertIn("Forecast", context)
        # Should contain temperature and pressure data
        self.assertIn("°C", context)
        self.assertIn("hPa", context)

    def test_pollen_bands_are_species_specific(self):
        """Same count must band differently per species (weeds are potent at low counts)"""
        self.assertEqual(self.builder_low._pollen_band("ragweed", 25.0), "high")
        self.assertEqual(self.builder_low._pollen_band("birch", 25.0), "low")
        self.assertEqual(self.builder_low._pollen_band("grass", 0.0), "none")
        self.assertEqual(self.builder_low._pollen_band("grass", 40.0), "moderate")
        self.assertEqual(self.builder_low._pollen_band("grass", 200.0), "very high")

    def test_hayfever_pollen_reports_band_not_peak(self):
        """Pollen summary must label the band and avoid calling the window max a 'peak'"""
        aq = [self._aq_row(grass_pollen=3.0, birch_pollen=1.0)]
        summary = self.builder_low._format_hayfever_pollen(aq)
        self.assertIn("Highest pollen band in this window: low", summary)
        self.assertIn("grass low (max 3", summary)
        self.assertNotIn("peak", summary)

    def test_hayfever_pollen_unavailable_outside_eu(self):
        """All-null pollen must be reported as unavailable rather than banded as none"""
        summary = self.builder_low._format_hayfever_pollen([self._aq_row()])
        self.assertIn("unavailable", summary)

    def test_hayfever_rain_line_states_washout(self):
        """Rain gets its own line so the wash-out signal is not buried"""
        line = self.builder_low._format_hayfever_rain(self.forecasts)
        self.assertIn("0.0 mm", line)
        self.assertIn("no rain", line)

        for forecast in self.forecasts:
            forecast.precipitation = 1.0
        line = self.builder_low._format_hayfever_rain(self.forecasts)
        self.assertIn("6.0 mm", line)
        self.assertIn("washes pollen out", line)

    def test_hayfever_species_context_is_labelled_as_calendar(self):
        """The seasonal calendar must not be presented as current pollen intensity"""
        from django.utils import timezone as tz

        context = self.builder_low._format_hayfever_species_context(51.5, tz.now())
        self.assertIn("calendar", context.lower())
        self.assertNotIn("peak", context.lower())

    def _aq_row(self, **pollen):
        """Build an unsaved AirQualityForecast carrying only the given pollen fields."""
        from forecast.models import AirQualityForecast

        now = timezone.now()
        return AirQualityForecast(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            pm2_5=6.0,
            pm10=12.0,
            ozone=55.0,
            nitrogen_dioxide=20.0,
            european_aqi=50.0,
            **pollen,
        )
