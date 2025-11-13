#!/usr/bin/env python
"""
LLM Prediction Test Suite - Manual Testing Only

This script tests LLM performance across various weather scenarios to:
1. Validate prediction accuracy against expected classifications
2. Compare different LLM models
3. Identify edge cases and inconsistencies
4. Store results for analysis and model comparison

IMPORTANT: This is a MANUAL testing tool, not part of the automated test suite.
The filename does NOT start with "test_" to prevent pytest from auto-discovering it.

Usage:
    python run_llm_tests.py [--model MODEL_NAME] [--base-url URL]

Examples:
    # Test with current database configuration
    python run_llm_tests.py

    # Test specific model
    python run_llm_tests.py --model "gpt-4o-mini" --api-key "sk-..."

    # Compare multiple models
    python run_llm_tests.py --model "model1"
    python run_llm_tests.py --model "model2"
    python analyze_llm_results.py llm_results/*.json
"""
import os
import sys
import json
import django
from datetime import datetime
from pathlib import Path

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "migraine_project.settings")
django.setup()

from forecast.llm_client import LLMClient
from forecast.prediction_service import MigrainePredictionService
from forecast.prediction_service_sinusitis import SinusitisPredictionService


# Test scenarios with expected outcomes
MIGRAINE_TEST_SCENARIOS = [
    {
        "name": "Clear LOW - Minimal risk",
        "description": "Perfect weather, no risk factors",
        "expected": "LOW",
        "scores": {
            "temperature_change": 0.0,
            "humidity_extreme": 0.0,
            "pressure_change": 0.0,
            "pressure_low": 0.0,
            "precipitation": 0.0,
            "cloud_cover": 0.0,
        },
        "context": {
            "aggregates": {
                "avg_forecast_temperature": 20.0,
                "avg_forecast_humidity": 50.0,
                "avg_forecast_pressure": 1013.0,
            }
        }
    },
    {
        "name": "Clear HIGH - Multiple severe factors",
        "description": "Major pressure drop + large temp change + high humidity",
        "expected": "HIGH",
        "scores": {
            "temperature_change": 0.9,  # 0.9 × 0.25 = 0.225
            "humidity_extreme": 0.85,   # 0.85 × 0.15 = 0.128
            "pressure_change": 0.95,    # 0.95 × 0.30 = 0.285
            "pressure_low": 0.8,        # 0.8 × 0.15 = 0.120
            "precipitation": 0.6,       # 0.6 × 0.05 = 0.030
            "cloud_cover": 0.9,         # 0.9 × 0.10 = 0.090
        },  # Total: 0.878 (HIGH)
        "context": {
            "aggregates": {
                "avg_forecast_temperature": 8.0,
                "avg_forecast_humidity": 92.0,
                "avg_forecast_pressure": 992.0,
            }
        }
    },
    {
        "name": "Boundary MEDIUM (low end)",
        "description": "Just above LOW threshold (0.40)",
        "expected": "MEDIUM",
        "scores": {
            "temperature_change": 0.4,  # 0.4 × 0.25 = 0.100
            "humidity_extreme": 0.5,    # 0.5 × 0.15 = 0.075
            "pressure_change": 0.5,     # 0.5 × 0.30 = 0.150
            "pressure_low": 0.3,        # 0.3 × 0.15 = 0.045
            "precipitation": 0.2,       # 0.2 × 0.05 = 0.010
            "cloud_cover": 0.4,         # 0.4 × 0.10 = 0.040
        },  # Total: 0.42 (MEDIUM)
        "context": {
            "aggregates": {
                "avg_forecast_temperature": 15.0,
                "avg_forecast_humidity": 72.0,
                "avg_forecast_pressure": 1003.0,
            }
        }
    },
    {
        "name": "Boundary MEDIUM (high end)",
        "description": "Just below HIGH threshold (0.70)",
        "expected": "MEDIUM",
        "scores": {
            "temperature_change": 0.7,  # 0.7 × 0.25 = 0.175
            "humidity_extreme": 0.75,   # 0.75 × 0.15 = 0.113
            "pressure_change": 0.8,     # 0.8 × 0.30 = 0.240
            "pressure_low": 0.6,        # 0.6 × 0.15 = 0.090
            "precipitation": 0.4,       # 0.4 × 0.05 = 0.020
            "cloud_cover": 0.7,         # 0.7 × 0.10 = 0.070
        },  # Total: 0.708 - but should be interpreted as MEDIUM edge case
        "context": {
            "aggregates": {
                "avg_forecast_temperature": 10.0,
                "avg_forecast_humidity": 85.0,
                "avg_forecast_pressure": 998.0,
            }
        }
    },
    {
        "name": "Boundary HIGH (low end)",
        "description": "Just at HIGH threshold (0.70)",
        "expected": "HIGH",
        "scores": {
            "temperature_change": 0.75, # 0.75 × 0.25 = 0.188
            "humidity_extreme": 0.8,    # 0.8 × 0.15 = 0.120
            "pressure_change": 0.85,    # 0.85 × 0.30 = 0.255
            "pressure_low": 0.7,        # 0.7 × 0.15 = 0.105
            "precipitation": 0.5,       # 0.5 × 0.05 = 0.025
            "cloud_cover": 0.8,         # 0.8 × 0.10 = 0.080
        },  # Total: 0.773 (HIGH)
        "context": {
            "aggregates": {
                "avg_forecast_temperature": 7.0,
                "avg_forecast_humidity": 88.0,
                "avg_forecast_pressure": 995.0,
            }
        }
    },
    {
        "name": "High pressure change only",
        "description": "Single dominant factor (pressure change 30% weight)",
        "expected": "MEDIUM",
        "scores": {
            "temperature_change": 0.1,
            "humidity_extreme": 0.1,
            "pressure_change": 0.95,    # 0.95 × 0.30 = 0.285
            "pressure_low": 0.2,
            "precipitation": 0.1,
            "cloud_cover": 0.3,
        },  # Total: ~0.35 (LOW, but close to MEDIUM)
        "context": {
            "aggregates": {
                "avg_forecast_temperature": 18.0,
                "avg_forecast_humidity": 55.0,
                "avg_forecast_pressure": 1008.0,
            }
        }
    },
    {
        "name": "London example (reported as HIGH)",
        "description": "Real-world case that was misclassified",
        "expected": "MEDIUM",
        "scores": {
            "cloud_cover": 1.0,         # 1.0 × 0.10 = 0.100
            "humidity_extreme": 0.53,   # 0.53 × 0.15 = 0.080
            "precipitation": 0.18,      # 0.18 × 0.05 = 0.009
            "pressure_change": 0.71,    # 0.71 × 0.30 = 0.213
            "pressure_low": 0.26,       # 0.26 × 0.15 = 0.039
            "temperature_change": 0.11, # 0.11 × 0.25 = 0.028
        },  # Total: 0.469 (MEDIUM)
        "context": {
            "aggregates": {
                "avg_forecast_temperature": 12.9,
                "avg_forecast_humidity": 84.0,
                "avg_forecast_pressure": 1001.2,
            }
        }
    },
    {
        "name": "Thessaloniki example (reported as HIGH)",
        "description": "Real-world case with weighted score 0.36",
        "expected": "LOW",
        "scores": {
            "cloud_cover": 1.0,         # 1.0 × 0.10 = 0.100
            "humidity_extreme": 0.81,   # 0.81 × 0.15 = 0.122
            "precipitation": 0.42,      # 0.42 × 0.05 = 0.021
            "pressure_change": 0.41,    # 0.41 × 0.30 = 0.123
            "pressure_low": 0.0,        # 0.0 × 0.15 = 0.000
            "temperature_change": 0.04, # 0.04 × 0.25 = 0.010
        },  # Total: 0.376 (LOW)
        "context": {
            "aggregates": {
                "avg_forecast_temperature": 15.5,
                "avg_forecast_humidity": 94.0,
                "avg_forecast_pressure": 1010.2,
            }
        }
    },
]

SINUSITIS_TEST_SCENARIOS = [
    {
        "name": "Clear LOW - Minimal risk",
        "description": "Perfect weather for sinuses",
        "expected": "LOW",
        "scores": {
            "temperature_change": 0.0,
            "humidity_extreme": 0.0,
            "pressure_change": 0.0,
            "pressure_low": 0.0,
            "precipitation": 0.0,
            "cloud_cover": 0.0,
        },
        "context": {
            "aggregates": {
                "avg_forecast_temperature": 20.0,
                "avg_forecast_humidity": 50.0,
                "avg_forecast_pressure": 1013.0,
            }
        }
    },
    {
        "name": "Clear HIGH - Humidity and temp change",
        "description": "High humidity + temperature change (key sinusitis triggers)",
        "expected": "HIGH",
        "scores": {
            "temperature_change": 0.9,  # 0.9 × 0.30 = 0.270
            "humidity_extreme": 0.95,   # 0.95 × 0.25 = 0.238
            "pressure_change": 0.7,     # 0.7 × 0.20 = 0.140
            "pressure_low": 0.5,        # 0.5 × 0.10 = 0.050
            "precipitation": 0.8,       # 0.8 × 0.10 = 0.080
            "cloud_cover": 0.6,         # 0.6 × 0.05 = 0.030
        },  # Total: 0.808 (HIGH)
        "context": {
            "aggregates": {
                "avg_forecast_temperature": 8.0,
                "avg_forecast_humidity": 92.0,
                "avg_forecast_pressure": 998.0,
            }
        }
    },
    {
        "name": "Boundary MEDIUM (sinusitis)",
        "description": "Just above LOW threshold (0.35)",
        "expected": "MEDIUM",
        "scores": {
            "temperature_change": 0.4,  # 0.4 × 0.30 = 0.120
            "humidity_extreme": 0.5,    # 0.5 × 0.25 = 0.125
            "pressure_change": 0.3,     # 0.3 × 0.20 = 0.060
            "pressure_low": 0.2,        # 0.2 × 0.10 = 0.020
            "precipitation": 0.3,       # 0.3 × 0.10 = 0.030
            "cloud_cover": 0.2,         # 0.2 × 0.05 = 0.010
        },  # Total: 0.365 (MEDIUM)
        "context": {
            "aggregates": {
                "avg_forecast_temperature": 15.0,
                "avg_forecast_humidity": 75.0,
                "avg_forecast_pressure": 1002.0,
            }
        }
    },
]


def calculate_weighted_score(scores, weights):
    """Calculate weighted score from individual factor scores."""
    total = 0.0
    for factor in ["temperature_change", "humidity_extreme", "pressure_change",
                   "pressure_low", "precipitation", "cloud_cover"]:
        total += scores.get(factor, 0) * weights.get(factor, 0)
    return round(total, 3)


def get_expected_classification(weighted_score, prediction_type="migraine", sensitivity_overall=1.0):
    """
    Determine expected classification based on weighted score and thresholds.

    Args:
        weighted_score: The calculated weighted score (0-1)
        prediction_type: "migraine" or "sinusitis"
        sensitivity_overall: User sensitivity multiplier (default 1.0)

    Returns:
        Expected classification: "LOW", "MEDIUM", or "HIGH"
    """
    if prediction_type == "migraine":
        high_thr = 0.7
        med_thr = 0.4
    else:  # sinusitis
        high_thr = 0.65
        med_thr = 0.35

    # Apply sensitivity adjustment
    shift = (sensitivity_overall - 1.0) * 0.15
    high_thr = min(max(high_thr - shift, 0.5 if prediction_type == "migraine" else 0.45),
                   0.9 if prediction_type == "migraine" else 0.85)
    med_thr = min(max(med_thr - shift, 0.25 if prediction_type == "migraine" else 0.20),
                  0.7 if prediction_type == "migraine" else 0.65)

    if weighted_score >= high_thr:
        return "HIGH"
    elif weighted_score >= med_thr:
        return "MEDIUM"
    else:
        return "LOW"


def run_test_scenario(client, scenario, prediction_type="migraine", sensitivity_overall=1.0):
    """
    Run a single test scenario and return results.

    Args:
        client: LLMClient instance
        scenario: Test scenario dictionary
        prediction_type: "migraine" or "sinusitis"
        sensitivity_overall: User sensitivity multiplier

    Returns:
        Dictionary with test results
    """
    # Get appropriate weights
    if prediction_type == "migraine":
        weights = dict(MigrainePredictionService.WEIGHTS)
    else:
        weights = dict(SinusitisPredictionService.WEIGHTS)

    # Add weights to scores
    scores = dict(scenario["scores"])
    scores["weights"] = weights

    # Calculate weighted score
    weighted_score = calculate_weighted_score(scenario["scores"], weights)

    # Get expected classification
    expected = get_expected_classification(weighted_score, prediction_type, sensitivity_overall)

    # Prepare user profile if sensitivity is not default
    user_profile = None
    if sensitivity_overall != 1.0:
        user_profile = {
            "sensitivity_overall": sensitivity_overall,
            "sensitivity_temperature": 1.0,
            "sensitivity_humidity": 1.0,
            "sensitivity_pressure": 1.0,
            "sensitivity_cloud_cover": 1.0,
            "sensitivity_precipitation": 1.0,
            "language": "en",
        }

    # Call LLM
    location_label = f"Test: {scenario['name']}"

    try:
        if prediction_type == "migraine":
            level, detail = client.predict_probability(
                scores=scores,
                location_label=location_label,
                user_profile=user_profile,
                context=scenario.get("context", {})
            )
        else:
            level, detail = client.predict_sinusitis_probability(
                scores=scores,
                location_label=location_label,
                user_profile=user_profile,
                context=scenario.get("context", {})
            )

        # Extract rationale and confidence if available
        rationale = None
        confidence = None
        analysis = None

        if detail and "raw" in detail:
            raw = detail["raw"]
            rationale = raw.get("rationale", "")
            confidence = raw.get("confidence", None)
            analysis = raw.get("analysis_text", "")

        return {
            "scenario_name": scenario["name"],
            "description": scenario["description"],
            "weighted_score": weighted_score,
            "expected": expected,
            "predicted": level,
            "correct": level == expected,
            "confidence": confidence,
            "rationale": rationale,
            "analysis": analysis,
            "error": None,
        }

    except Exception as e:
        return {
            "scenario_name": scenario["name"],
            "description": scenario["description"],
            "weighted_score": weighted_score,
            "expected": expected,
            "predicted": None,
            "correct": False,
            "confidence": None,
            "rationale": None,
            "analysis": None,
            "error": str(e),
        }



def run_test_suite(model_name, base_url, api_key=None, timeout=120):
    """
    Run the complete test suite for a given LLM model.

    Args:
        model_name: Name of the LLM model to test
        base_url: Base URL for the LLM API
        api_key: API key (optional for local models)
        timeout: Request timeout in seconds

    Returns:
        Dictionary with complete test results
    """
    print("=" * 80)
    print(f"LLM PREDICTION TEST SUITE")
    print("=" * 80)
    print(f"\nModel: {model_name}")
    print(f"Base URL: {base_url}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("\n" + "=" * 80)

    # Create LLM client
    client = LLMClient(
        base_url=base_url,
        api_key=api_key or "not-needed",
        model=model_name,
        timeout=timeout,
    )

    results = {
        "model": model_name,
        "base_url": base_url,
        "timestamp": datetime.now().isoformat(),
        "migraine_tests": [],
        "sinusitis_tests": [],
        "summary": {},
    }

    # Test migraine scenarios
    print("\n" + "=" * 80)
    print("MIGRAINE PREDICTION TESTS")
    print("=" * 80)

    for i, scenario in enumerate(MIGRAINE_TEST_SCENARIOS, 1):
        print(f"\n[{i}/{len(MIGRAINE_TEST_SCENARIOS)}] Testing: {scenario['name']}")
        print(f"    Description: {scenario['description']}")

        result = run_test_scenario(client, scenario, "migraine")
        results["migraine_tests"].append(result)

        # Print result
        status = "✓ PASS" if result["correct"] else "✗ FAIL"
        print(f"    Weighted Score: {result['weighted_score']:.3f}")
        print(f"    Expected: {result['expected']} | Predicted: {result['predicted']} | {status}")

        if result["confidence"] is not None:
            print(f"    Confidence: {result['confidence']:.2f}")
        if result["error"]:
            print(f"    ERROR: {result['error']}")

    # Test sinusitis scenarios
    print("\n" + "=" * 80)
    print("SINUSITIS PREDICTION TESTS")
    print("=" * 80)

    for i, scenario in enumerate(SINUSITIS_TEST_SCENARIOS, 1):
        print(f"\n[{i}/{len(SINUSITIS_TEST_SCENARIOS)}] Testing: {scenario['name']}")
        print(f"    Description: {scenario['description']}")

        result = run_test_scenario(client, scenario, "sinusitis")
        results["sinusitis_tests"].append(result)

        # Print result
        status = "✓ PASS" if result["correct"] else "✗ FAIL"
        print(f"    Weighted Score: {result['weighted_score']:.3f}")
        print(f"    Expected: {result['expected']} | Predicted: {result['predicted']} | {status}")

        if result["confidence"] is not None:
            print(f"    Confidence: {result['confidence']:.2f}")
        if result["error"]:
            print(f"    ERROR: {result['error']}")

    # Calculate summary statistics
    migraine_correct = sum(1 for r in results["migraine_tests"] if r["correct"])
    migraine_total = len(results["migraine_tests"])
    migraine_errors = sum(1 for r in results["migraine_tests"] if r["error"])

    sinusitis_correct = sum(1 for r in results["sinusitis_tests"] if r["correct"])
    sinusitis_total = len(results["sinusitis_tests"])
    sinusitis_errors = sum(1 for r in results["sinusitis_tests"] if r["error"])

    total_correct = migraine_correct + sinusitis_correct
    total_tests = migraine_total + sinusitis_total
    total_errors = migraine_errors + sinusitis_errors

    results["summary"] = {
        "migraine_accuracy": migraine_correct / migraine_total if migraine_total > 0 else 0,
        "migraine_correct": migraine_correct,
        "migraine_total": migraine_total,
        "migraine_errors": migraine_errors,
        "sinusitis_accuracy": sinusitis_correct / sinusitis_total if sinusitis_total > 0 else 0,
        "sinusitis_correct": sinusitis_correct,
        "sinusitis_total": sinusitis_total,
        "sinusitis_errors": sinusitis_errors,
        "overall_accuracy": total_correct / total_tests if total_tests > 0 else 0,
        "total_correct": total_correct,
        "total_tests": total_tests,
        "total_errors": total_errors,
    }

    # Print summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"\nMigraine Tests:")
    print(f"  Accuracy: {results['summary']['migraine_accuracy']:.1%} ({migraine_correct}/{migraine_total})")
    print(f"  Errors: {migraine_errors}")

    print(f"\nSinusitis Tests:")
    print(f"  Accuracy: {results['summary']['sinusitis_accuracy']:.1%} ({sinusitis_correct}/{sinusitis_total})")
    print(f"  Errors: {sinusitis_errors}")

    print(f"\nOverall:")
    print(f"  Accuracy: {results['summary']['overall_accuracy']:.1%} ({total_correct}/{total_tests})")
    print(f"  Total Errors: {total_errors}")

    return results


def save_results(results, output_dir="llm_results"):
    """
    Save test results to JSON file.

    Args:
        results: Test results dictionary
        output_dir: Directory to save results

    Returns:
        Path to saved file
    """
    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    # Generate filename with model name and timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_safe = results["model"].replace("/", "_").replace(":", "_")
    filename = f"{model_safe}_{timestamp}.json"
    filepath = output_path / filename

    # Save results
    with open(filepath, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✓ Results saved to: {filepath}")
    return str(filepath)




def compare_models(result_files):
    """
    Compare results from multiple model test runs.

    Args:
        result_files: List of paths to result JSON files

    Returns:
        Comparison summary
    """
    if not result_files:
        print("No result files provided for comparison")
        return

    print("\n" + "=" * 80)
    print("MODEL COMPARISON")
    print("=" * 80)

    models_data = []
    for filepath in result_files:
        with open(filepath, "r") as f:
            data = json.load(f)
            models_data.append(data)

    # Print comparison table
    print(f"\n{'Model':<40} {'Overall Acc':<15} {'Migraine Acc':<15} {'Sinusitis Acc':<15}")
    print("-" * 85)

    for data in models_data:
        model_name = data["model"][:38]  # Truncate long names
        overall = data["summary"]["overall_accuracy"]
        migraine = data["summary"]["migraine_accuracy"]
        sinusitis = data["summary"]["sinusitis_accuracy"]

        print(f"{model_name:<40} {overall:>6.1%} ({data['summary']['total_correct']}/{data['summary']['total_tests']})    "
              f"{migraine:>6.1%} ({data['summary']['migraine_correct']}/{data['summary']['migraine_total']})    "
              f"{sinusitis:>6.1%} ({data['summary']['sinusitis_correct']}/{data['summary']['sinusitis_total']})")

    # Find scenarios where models disagree
    print("\n" + "=" * 80)
    print("DISAGREEMENTS BETWEEN MODELS")
    print("=" * 80)

    if len(models_data) >= 2:
        # Compare migraine tests
        print("\nMigraine Predictions:")
        for i, scenario in enumerate(MIGRAINE_TEST_SCENARIOS):
            predictions = [data["migraine_tests"][i]["predicted"] for data in models_data]
            if len(set(predictions)) > 1:  # Models disagree
                print(f"\n  Scenario: {scenario['name']}")
                print(f"  Expected: {scenario['expected']}")
                for j, data in enumerate(models_data):
                    pred = data["migraine_tests"][i]["predicted"]
                    correct = "✓" if pred == scenario["expected"] else "✗"
                    print(f"    {data['model']}: {pred} {correct}")

        # Compare sinusitis tests
        print("\nSinusitis Predictions:")
        for i, scenario in enumerate(SINUSITIS_TEST_SCENARIOS):
            predictions = [data["sinusitis_tests"][i]["predicted"] for data in models_data]
            if len(set(predictions)) > 1:  # Models disagree
                print(f"\n  Scenario: {scenario['name']}")
                print(f"  Expected: {scenario['expected']}")
                for j, data in enumerate(models_data):
                    pred = data["sinusitis_tests"][i]["predicted"]
                    correct = "✓" if pred == scenario["expected"] else "✗"
                    print(f"    {data['model']}: {pred} {correct}")


def main():
    """
    Main entry point for manual test execution.

    This script is designed to be run manually, not as part of automated testing.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="LLM Prediction Test Suite - Manual Testing Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with default local LLM server
  python run_llm_tests.py

  # Test with specific model
  python run_llm_tests.py --model "gpt-4o-mini"

  # Test with custom base URL
  python run_llm_tests.py --base-url "http://192.168.0.171:1234"

  # Compare multiple result files
  python run_llm_tests.py --compare llm_results/model1_*.json llm_results/model2_*.json

  # Test with API key
  python run_llm_tests.py --model "gpt-4o-mini" --api-key "sk-..."
        """
    )

    parser.add_argument(
        "--model",
        default=None,
        help="Model name to test (default: use current LLM configuration from database)"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:1234",
        help="Base URL for LLM API (default: http://localhost:1234)"
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for LLM service (optional for local models)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Request timeout in seconds (default: 120)"
    )
    parser.add_argument(
        "--compare",
        nargs="+",
        help="Compare multiple result files instead of running tests"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save results to file"
    )

    args = parser.parse_args()

    # If comparing results, do that and exit
    if args.compare:
        compare_models(args.compare)
        return

    # Get model name from database if not specified
    if args.model is None:
        from forecast.models import LLMConfiguration
        llm_config = LLMConfiguration.get_config()

        if not llm_config.is_active:
            print("ERROR: LLM is not active in database configuration!")
            print("Please activate an LLM configuration or specify --model")
            sys.exit(1)

        args.model = llm_config.model
        if args.base_url == "http://localhost:1234":  # Use DB URL if default wasn't changed
            args.base_url = llm_config.base_url
        if args.api_key is None:
            args.api_key = llm_config.api_key

        print(f"Using LLM configuration from database:")
        print(f"  Model: {args.model}")
        print(f"  Base URL: {args.base_url}")

    # Run test suite
    results = run_test_suite(
        model_name=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout
    )

    # Save results unless --no-save specified
    if not args.no_save:
        save_results(results)

    # Print final status
    print("\n" + "=" * 80)
    accuracy = results["summary"]["overall_accuracy"]
    if accuracy >= 0.9:
        print("✓ EXCELLENT: Model performance is excellent (≥90% accuracy)")
    elif accuracy >= 0.75:
        print("✓ GOOD: Model performance is good (≥75% accuracy)")
    elif accuracy >= 0.6:
        print("⚠ FAIR: Model performance is fair (≥60% accuracy)")
    else:
        print("✗ POOR: Model performance needs improvement (<60% accuracy)")
    print("=" * 80)


if __name__ == "__main__":
    main()

