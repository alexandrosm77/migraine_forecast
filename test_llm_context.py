#!/usr/bin/env python
"""
Test script to validate LLM context builder with different weather scenarios.

Usage:
    python test_llm_context.py                    # Run all scenarios
    python test_llm_context.py --scenario 1       # Run specific scenario
    python test_llm_context.py --context-only     # Show context without calling LLM
    python test_llm_context.py --high-token       # Use high token budget

Scenarios:
    1. Pressure Drop Storm   - Rapid pressure drop with incoming storm (HIGH risk)
    2. Stable Conditions     - Calm, stable weather (LOW risk)
    3. Humidity Spike        - Sudden humidity increase (MEDIUM risk)
    4. Temperature Swing     - Large temperature change (MEDIUM-HIGH risk)
    5. Dry Cold Front        - Cold, dry air mass moving in (MEDIUM risk)
"""

import os
import argparse
import logging

# Setup Django first
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "migraine_project.settings")

import django  # noqa: E402
django.setup()

# Suppress logging for cleaner output (must be after django.setup())
logging.getLogger('forecast.llm_client').setLevel(logging.CRITICAL)
logging.getLogger('forecast.llm_context_builder').setLevel(logging.CRITICAL)
logging.getLogger('django').setLevel(logging.CRITICAL)
logging.getLogger().setLevel(logging.CRITICAL)  # Root logger

from datetime import timedelta  # noqa: E402
from django.utils import timezone  # noqa: E402
from forecast.llm_client import LLMClient  # noqa: E402
from forecast.llm_context_builder import LLMContextBuilder  # noqa: E402


# ANSI colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


class MockForecast:
    """Mock forecast object for testing without database."""
    def __init__(self, target_time, temperature, pressure, humidity, precipitation=0, cloud_cover=50, wind_speed=10):
        self.target_time = target_time
        self.temperature = temperature
        self.pressure = pressure
        self.humidity = humidity
        self.precipitation = precipitation
        self.cloud_cover = cloud_cover
        self.wind_speed = wind_speed


class MockLocation:
    """Mock location object for testing."""
    def __init__(self, city, country, latitude, longitude):
        self.city = city
        self.country = country
        self.latitude = latitude
        self.longitude = longitude


class MockPrediction:
    """Mock prediction object for testing."""
    def __init__(self, prediction_time, probability, target_time_start):
        self.prediction_time = prediction_time
        self.probability = probability
        self.target_time_start = target_time_start


# =============================================================================
# WEATHER SCENARIOS
# =============================================================================

SCENARIOS = {}


def scenario(num, name, expected_risk, description):
    """Decorator to register a scenario."""
    def decorator(func):
        SCENARIOS[num] = {
            "name": name,
            "expected_risk": expected_risk,
            "description": description,
            "create_data": func,
        }
        return func
    return decorator


@scenario(1, "Pressure Drop Storm", "HIGH",
          "Rapid barometric pressure drop with incoming storm system")
def create_pressure_drop_scenario():
    """Scenario 1: Rapid pressure drop - classic migraine trigger."""
    now = timezone.now()
    location = MockLocation("London", "UK", 51.5074, -0.1278)

    # Forecast: Pressure dropping rapidly, humidity rising, rain coming
    forecasts = [
        MockForecast(now + timedelta(hours=3), 14.0, 1005.0, 78, 0.0, 70, 15),
        MockForecast(now + timedelta(hours=4), 13.5, 1002.0, 82, 0.5, 85, 20),
        MockForecast(now + timedelta(hours=5), 13.0, 999.0, 88, 2.0, 95, 25),
        MockForecast(now + timedelta(hours=6), 12.5, 996.0, 92, 4.0, 100, 30),
    ]

    # Previous: Stable high pressure
    previous_forecasts = [
        MockForecast(now - timedelta(hours=6), 15.0, 1018.0, 55, 0, 30, 8),
        MockForecast(now - timedelta(hours=5), 15.5, 1017.0, 58, 0, 35, 9),
        MockForecast(now - timedelta(hours=4), 15.0, 1016.0, 60, 0, 40, 10),
        MockForecast(now - timedelta(hours=3), 14.5, 1014.0, 65, 0, 50, 12),
        MockForecast(now - timedelta(hours=2), 14.0, 1012.0, 70, 0, 60, 13),
        MockForecast(now - timedelta(hours=1), 14.0, 1008.0, 75, 0, 65, 14),
    ]

    user_profile = {
        "sensitivity_overall": 1.3,
        "sensitivity_pressure": 1.5,
        "sensitivity_temperature": 1.0,
        "sensitivity_humidity": 1.2,
    }

    return location, forecasts, previous_forecasts, [], user_profile


@scenario(2, "Stable Conditions", "LOW",
          "Calm, stable weather with minimal changes")
def create_stable_scenario():
    """Scenario 2: Stable conditions - low risk."""
    now = timezone.now()
    location = MockLocation("San Diego", "USA", 32.7157, -117.1611)

    # Forecast: Very stable, typical San Diego weather
    forecasts = [
        MockForecast(now + timedelta(hours=3), 22.0, 1015.0, 55, 0, 20, 8),
        MockForecast(now + timedelta(hours=4), 22.5, 1015.0, 53, 0, 15, 7),
        MockForecast(now + timedelta(hours=5), 23.0, 1015.0, 50, 0, 10, 6),
        MockForecast(now + timedelta(hours=6), 22.5, 1015.0, 52, 0, 15, 7),
    ]

    # Previous: Also stable
    previous_forecasts = [
        MockForecast(now - timedelta(hours=6), 20.0, 1015.0, 58, 0, 25, 8),
        MockForecast(now - timedelta(hours=5), 20.5, 1015.0, 56, 0, 22, 8),
        MockForecast(now - timedelta(hours=4), 21.0, 1015.0, 55, 0, 20, 7),
        MockForecast(now - timedelta(hours=3), 21.5, 1015.0, 54, 0, 18, 7),
        MockForecast(now - timedelta(hours=2), 22.0, 1015.0, 53, 0, 16, 7),
        MockForecast(now - timedelta(hours=1), 22.0, 1015.0, 54, 0, 18, 8),
    ]

    user_profile = {
        "sensitivity_overall": 1.0,
        "sensitivity_pressure": 1.0,
        "sensitivity_temperature": 1.0,
        "sensitivity_humidity": 1.0,
    }

    return location, forecasts, previous_forecasts, [], user_profile


@scenario(3, "Humidity Spike", "MEDIUM",
          "Sudden humidity increase with approaching moisture")
def create_humidity_spike_scenario():
    """Scenario 3: Humidity spike - sinusitis trigger."""
    now = timezone.now()
    location = MockLocation("Miami", "USA", 25.7617, -80.1918)

    # Forecast: Humidity spiking, tropical moisture
    forecasts = [
        MockForecast(now + timedelta(hours=3), 28.0, 1012.0, 75, 0, 60, 12),
        MockForecast(now + timedelta(hours=4), 28.5, 1011.0, 82, 0.5, 75, 14),
        MockForecast(now + timedelta(hours=5), 29.0, 1010.0, 90, 1.0, 85, 15),
        MockForecast(now + timedelta(hours=6), 28.5, 1010.0, 95, 2.0, 95, 16),
    ]

    # Previous: Moderate humidity
    previous_forecasts = [
        MockForecast(now - timedelta(hours=6), 26.0, 1014.0, 60, 0, 30, 10),
        MockForecast(now - timedelta(hours=5), 27.0, 1013.0, 62, 0, 35, 10),
        MockForecast(now - timedelta(hours=4), 27.5, 1013.0, 65, 0, 40, 11),
        MockForecast(now - timedelta(hours=3), 28.0, 1012.0, 68, 0, 50, 11),
        MockForecast(now - timedelta(hours=2), 28.0, 1012.0, 70, 0, 55, 12),
        MockForecast(now - timedelta(hours=1), 28.0, 1012.0, 72, 0, 58, 12),
    ]

    user_profile = {
        "sensitivity_overall": 1.2,
        "sensitivity_pressure": 1.0,
        "sensitivity_temperature": 1.0,
        "sensitivity_humidity": 1.5,
    }

    return location, forecasts, previous_forecasts, [], user_profile


@scenario(4, "Temperature Swing", "MEDIUM-HIGH",
          "Large temperature drop as cold front passes")
def create_temp_swing_scenario():
    """Scenario 4: Temperature swing - migraine trigger."""
    now = timezone.now()
    location = MockLocation("Denver", "USA", 39.7392, -104.9903)

    # Forecast: Temperature dropping sharply (cold front)
    forecasts = [
        MockForecast(now + timedelta(hours=3), 18.0, 1010.0, 45, 0, 40, 20),
        MockForecast(now + timedelta(hours=4), 12.0, 1012.0, 50, 0, 50, 25),
        MockForecast(now + timedelta(hours=5), 6.0, 1014.0, 55, 0.2, 60, 30),
        MockForecast(now + timedelta(hours=6), 2.0, 1016.0, 60, 0.5, 70, 28),
    ]

    # Previous: Warm afternoon
    previous_forecasts = [
        MockForecast(now - timedelta(hours=6), 22.0, 1008.0, 35, 0, 20, 12),
        MockForecast(now - timedelta(hours=5), 24.0, 1008.0, 32, 0, 15, 10),
        MockForecast(now - timedelta(hours=4), 25.0, 1008.0, 30, 0, 10, 8),
        MockForecast(now - timedelta(hours=3), 24.0, 1008.0, 32, 0, 15, 10),
        MockForecast(now - timedelta(hours=2), 22.0, 1009.0, 38, 0, 25, 15),
        MockForecast(now - timedelta(hours=1), 20.0, 1009.0, 42, 0, 35, 18),
    ]

    user_profile = {
        "sensitivity_overall": 1.2,
        "sensitivity_pressure": 1.0,
        "sensitivity_temperature": 1.5,
        "sensitivity_humidity": 1.0,
    }

    return location, forecasts, previous_forecasts, [], user_profile


@scenario(5, "Dry Cold Front", "MEDIUM",
          "Cold, dry air mass - sinusitis risk from dry air")
def create_dry_cold_scenario():
    """Scenario 5: Dry cold front - sinusitis trigger from dry air."""
    now = timezone.now()
    location = MockLocation("Chicago", "USA", 41.8781, -87.6298)

    # Forecast: Cold and very dry
    forecasts = [
        MockForecast(now + timedelta(hours=3), 0.0, 1025.0, 30, 0, 10, 20),
        MockForecast(now + timedelta(hours=4), -2.0, 1026.0, 25, 0, 5, 22),
        MockForecast(now + timedelta(hours=5), -4.0, 1027.0, 22, 0, 0, 25),
        MockForecast(now + timedelta(hours=6), -5.0, 1028.0, 20, 0, 0, 23),
    ]

    # Previous: Milder, more humid
    previous_forecasts = [
        MockForecast(now - timedelta(hours=6), 8.0, 1018.0, 55, 0, 40, 12),
        MockForecast(now - timedelta(hours=5), 6.0, 1020.0, 50, 0, 35, 14),
        MockForecast(now - timedelta(hours=4), 4.0, 1021.0, 45, 0, 25, 16),
        MockForecast(now - timedelta(hours=3), 3.0, 1022.0, 40, 0, 20, 18),
        MockForecast(now - timedelta(hours=2), 2.0, 1023.0, 35, 0, 15, 19),
        MockForecast(now - timedelta(hours=1), 1.0, 1024.0, 32, 0, 12, 20),
    ]

    user_profile = {
        "sensitivity_overall": 1.1,
        "sensitivity_pressure": 1.2,
        "sensitivity_temperature": 1.3,
        "sensitivity_humidity": 1.4,
    }

    return location, forecasts, previous_forecasts, [], user_profile


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def print_header(text, char="="):
    """Print a formatted header."""
    width = 70
    print(f"\n{Colors.BOLD}{char * width}{Colors.ENDC}")
    print(f"{Colors.BOLD}{text.center(width)}{Colors.ENDC}")
    print(f"{Colors.BOLD}{char * width}{Colors.ENDC}")


def print_subheader(text):
    """Print a formatted subheader."""
    print(f"\n{Colors.CYAN}▶ {text}{Colors.ENDC}")
    print(f"{Colors.CYAN}{'-' * 50}{Colors.ENDC}")


def color_risk(level):
    """Color-code risk level."""
    colors = {
        "LOW": Colors.GREEN,
        "MEDIUM": Colors.YELLOW,
        "HIGH": Colors.RED,
    }
    color = colors.get(level, Colors.ENDC)
    return f"{color}{Colors.BOLD}{level}{Colors.ENDC}"


def print_result(condition, level, detail):
    """Print a formatted prediction result."""
    print(f"\n  {Colors.BOLD}{condition} Risk:{Colors.ENDC} {color_risk(level)}")

    if detail and "raw" in detail:
        raw = detail["raw"]
        confidence = raw.get('confidence', 'N/A')
        if isinstance(confidence, float):
            confidence = f"{confidence:.0%}"
        print(f"  {Colors.BLUE}Confidence:{Colors.ENDC} {confidence}")

        rationale = raw.get('rationale', 'N/A')
        if rationale and rationale != 'N/A':
            # Word wrap rationale
            words = rationale.split()
            lines = []
            current_line = []
            for word in words:
                current_line.append(word)
                if len(' '.join(current_line)) > 60:
                    lines.append(' '.join(current_line[:-1]))
                    current_line = [word]
            if current_line:
                lines.append(' '.join(current_line))
            print(f"  {Colors.BLUE}Rationale:{Colors.ENDC}")
            for line in lines:
                print(f"    {line}")

        tips = raw.get('prevention_tips', [])
        if tips:
            print(f"  {Colors.BLUE}Prevention Tips:{Colors.ENDC}")
            for tip in tips[:3]:  # Limit to 3 tips
                print(f"    • {tip}")


def print_context(context, label):
    """Print formatted context."""
    print(f"\n{Colors.HEADER}[{label} Context]{Colors.ENDC}")
    for line in context.split('\n'):
        print(f"  {line}")


# =============================================================================
# TEST FUNCTIONS
# =============================================================================

def run_scenario(scenario_num, base_url, model, high_token=False, context_only=False):
    """Run a single scenario."""
    if scenario_num not in SCENARIOS:
        print(f"{Colors.RED}Error: Scenario {scenario_num} not found{Colors.ENDC}")
        return

    scenario = SCENARIOS[scenario_num]
    location, forecasts, previous_forecasts, previous_predictions, user_profile = scenario["create_data"]()

    # Print scenario header
    print_header(f"Scenario {scenario_num}: {scenario['name']}")
    print(f"\n{Colors.BOLD}Description:{Colors.ENDC} {scenario['description']}")
    print(f"{Colors.BOLD}Expected Risk:{Colors.ENDC} {color_risk(scenario['expected_risk'])}")
    print(f"{Colors.BOLD}Location:{Colors.ENDC} {location.city}, {location.country} ({location.latitude:.1f}°N)")
    print(f"{Colors.BOLD}Token Budget:{Colors.ENDC} {'High' if high_token else 'Low'}")

    # Build context
    builder = LLMContextBuilder(high_token_budget=high_token)

    migraine_ctx = builder.build_migraine_context(
        forecasts=forecasts,
        previous_forecasts=previous_forecasts,
        location=location,
        user_profile=user_profile,
        previous_predictions=previous_predictions,
    )

    # Show context
    print_subheader("Generated Context")
    print_context(migraine_ctx, "Migraine")

    if context_only:
        return

    # Call LLM
    print_subheader("LLM Predictions")
    print(f"  Calling {model}...")

    client = LLMClient(base_url=base_url, model=model, timeout=120.0)

    # Migraine prediction
    try:
        level, detail = client.predict_probability(
            scores={},
            location_label=f"{location.city}, {location.country}",
            user_profile=user_profile,
            forecasts=forecasts,
            previous_forecasts=previous_forecasts,
            location=location,
            previous_predictions=previous_predictions,
            high_token_budget=high_token,
        )
        print_result("Migraine", level, detail)
    except Exception as e:
        print(f"  {Colors.RED}Migraine prediction failed: {e}{Colors.ENDC}")

    # Sinusitis prediction
    try:
        level, detail = client.predict_sinusitis_probability(
            scores={},
            location_label=f"{location.city}, {location.country}",
            user_profile=user_profile,
            forecasts=forecasts,
            previous_forecasts=previous_forecasts,
            location=location,
            previous_predictions=previous_predictions,
            high_token_budget=high_token,
        )
        print_result("Sinusitis", level, detail)
    except Exception as e:
        print(f"  {Colors.RED}Sinusitis prediction failed: {e}{Colors.ENDC}")


def list_scenarios():
    """List all available scenarios."""
    print_header("Available Weather Scenarios")
    print()
    for num, scenario in sorted(SCENARIOS.items()):
        risk_colored = color_risk(scenario['expected_risk'])
        print(f"  {Colors.BOLD}{num}.{Colors.ENDC} {scenario['name']}")
        print(f"     Expected: {risk_colored}")
        print(f"     {scenario['description']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Test LLM context builder with different weather scenarios",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_llm_context.py                    # Run all scenarios
  python test_llm_context.py --scenario 1       # Run scenario 1 only
  python test_llm_context.py --list             # List all scenarios
  python test_llm_context.py --context-only     # Show context without LLM
  python test_llm_context.py --high-token       # Use detailed context
        """
    )
    parser.add_argument("--url", default="http://192.168.0.171:1234",
                        help="LLM API base URL (default: http://192.168.0.171:1234)")
    parser.add_argument("--model", default="granite-4.0-h-tiny-mlx",
                        help="Model name (default: granite-4.0-h-tiny-mlx)")
    parser.add_argument("--high-token", action="store_true",
                        help="Use high token budget (more detailed context)")
    parser.add_argument("--context-only", action="store_true",
                        help="Only show context, don't call LLM")
    parser.add_argument("--scenario", type=int, metavar="N",
                        help="Run specific scenario (1-5)")
    parser.add_argument("--list", action="store_true",
                        help="List all available scenarios")
    args = parser.parse_args()

    if args.list:
        list_scenarios()
        return

    print_header("LLM Weather Context Tester", "═")
    print(f"\n{Colors.BOLD}Configuration:{Colors.ENDC}")
    print(f"  API URL: {args.url}")
    print(f"  Model: {args.model}")
    print(f"  Token Budget: {'High' if args.high_token else 'Low'}")
    print(f"  Mode: {'Context Only' if args.context_only else 'Full LLM Test'}")

    if args.scenario:
        # Run single scenario
        run_scenario(args.scenario, args.url, args.model, args.high_token, args.context_only)
    else:
        # Run all scenarios
        for num in sorted(SCENARIOS.keys()):
            run_scenario(num, args.url, args.model, args.high_token, args.context_only)

    # Summary
    print_header("Test Complete", "═")
    print(f"\n{Colors.GREEN}✓ All scenarios processed{Colors.ENDC}\n")


if __name__ == "__main__":
    main()
