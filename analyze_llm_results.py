#!/usr/bin/env python
"""
LLM Results Analysis and Visualization

This script analyzes test results from the LLM prediction test suite and generates
detailed reports comparing model performance.

Usage:
    python analyze_llm_results.py [result_files...]
    python analyze_llm_results.py llm_results/*.json
"""
import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict


def load_results(filepaths):
    """Load all result files."""
    results = []
    for filepath in filepaths:
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                data["filepath"] = filepath
                results.append(data)
        except Exception as e:
            print(f"Warning: Could not load {filepath}: {e}")
    return results


def generate_summary_report(results):
    """Generate a summary report of all test results."""
    print("\n" + "=" * 100)
    print("LLM MODEL PERFORMANCE SUMMARY")
    print("=" * 100)
    
    # Sort by overall accuracy (descending)
    results_sorted = sorted(results, key=lambda x: x["summary"]["overall_accuracy"], reverse=True)
    
    # Print header
    print(f"\n{'Rank':<6} {'Model':<35} {'Timestamp':<20} {'Overall':<12} {'Migraine':<12} {'Sinusitis':<12}")
    print("-" * 100)
    
    # Print each model
    for i, data in enumerate(results_sorted, 1):
        model = data["model"][:33]
        timestamp = data["timestamp"][:19]
        overall = f"{data['summary']['overall_accuracy']:.1%} ({data['summary']['total_correct']}/{data['summary']['total_tests']})"
        migraine = f"{data['summary']['migraine_accuracy']:.1%} ({data['summary']['migraine_correct']}/{data['summary']['migraine_total']})"
        sinusitis = f"{data['summary']['sinusitis_accuracy']:.1%} ({data['summary']['sinusitis_correct']}/{data['summary']['sinusitis_total']})"
        
        print(f"{i:<6} {model:<35} {timestamp:<20} {overall:<12} {migraine:<12} {sinusitis:<12}")
    
    print("\n" + "=" * 100)


def analyze_scenario_performance(results):
    """Analyze performance on each scenario across all models."""
    print("\n" + "=" * 100)
    print("SCENARIO-LEVEL ANALYSIS")
    print("=" * 100)
    
    # Analyze migraine scenarios
    print("\n" + "-" * 100)
    print("MIGRAINE SCENARIOS")
    print("-" * 100)
    
    # Get scenario names from first result
    if results and results[0]["migraine_tests"]:
        num_scenarios = len(results[0]["migraine_tests"])
        
        for i in range(num_scenarios):
            scenario_name = results[0]["migraine_tests"][i]["scenario_name"]
            expected = results[0]["migraine_tests"][i]["expected"]
            weighted_score = results[0]["migraine_tests"][i]["weighted_score"]
            
            # Count correct predictions across all models
            correct_count = sum(1 for r in results if r["migraine_tests"][i]["correct"])
            total_count = len(results)
            accuracy = correct_count / total_count if total_count > 0 else 0
            
            # Get all predictions
            predictions = [r["migraine_tests"][i]["predicted"] for r in results]
            prediction_counts = defaultdict(int)
            for pred in predictions:
                prediction_counts[pred] += 1
            
            print(f"\n{i+1}. {scenario_name}")
            print(f"   Expected: {expected} | Weighted Score: {weighted_score:.3f}")
            print(f"   Accuracy: {accuracy:.1%} ({correct_count}/{total_count} models correct)")
            print(f"   Predictions: {dict(prediction_counts)}")
            
            # Show which models got it wrong
            if correct_count < total_count:
                wrong_models = [r["model"] for r in results if not r["migraine_tests"][i]["correct"]]
                print(f"   Failed by: {', '.join(wrong_models[:3])}" + (" ..." if len(wrong_models) > 3 else ""))
    
    # Analyze sinusitis scenarios
    print("\n" + "-" * 100)
    print("SINUSITIS SCENARIOS")
    print("-" * 100)
    
    if results and results[0]["sinusitis_tests"]:
        num_scenarios = len(results[0]["sinusitis_tests"])
        
        for i in range(num_scenarios):
            scenario_name = results[0]["sinusitis_tests"][i]["scenario_name"]
            expected = results[0]["sinusitis_tests"][i]["expected"]
            weighted_score = results[0]["sinusitis_tests"][i]["weighted_score"]
            
            # Count correct predictions across all models
            correct_count = sum(1 for r in results if r["sinusitis_tests"][i]["correct"])
            total_count = len(results)
            accuracy = correct_count / total_count if total_count > 0 else 0
            
            # Get all predictions
            predictions = [r["sinusitis_tests"][i]["predicted"] for r in results]
            prediction_counts = defaultdict(int)
            for pred in predictions:
                prediction_counts[pred] += 1
            
            print(f"\n{i+1}. {scenario_name}")
            print(f"   Expected: {expected} | Weighted Score: {weighted_score:.3f}")
            print(f"   Accuracy: {accuracy:.1%} ({correct_count}/{total_count} models correct)")
            print(f"   Predictions: {dict(prediction_counts)}")
            
            # Show which models got it wrong
            if correct_count < total_count:
                wrong_models = [r["model"] for r in results if not r["sinusitis_tests"][i]["correct"]]
                print(f"   Failed by: {', '.join(wrong_models[:3])}" + (" ..." if len(wrong_models) > 3 else ""))
    
    print("\n" + "=" * 100)


def identify_problematic_scenarios(results):
    """Identify scenarios that are consistently difficult for models."""
    print("\n" + "=" * 100)
    print("PROBLEMATIC SCENARIOS (Low Success Rate)")
    print("=" * 100)
    
    if not results:
        print("No results to analyze")
        return
    
    problematic = []
    
    # Check migraine scenarios
    if results[0]["migraine_tests"]:
        for i in range(len(results[0]["migraine_tests"])):
            correct_count = sum(1 for r in results if r["migraine_tests"][i]["correct"])
            total_count = len(results)
            accuracy = correct_count / total_count if total_count > 0 else 0
            
            if accuracy < 0.5:  # Less than 50% of models get it right
                scenario = results[0]["migraine_tests"][i]
                problematic.append({
                    "type": "Migraine",
                    "name": scenario["scenario_name"],
                    "expected": scenario["expected"],
                    "weighted_score": scenario["weighted_score"],
                    "accuracy": accuracy,
                    "correct": correct_count,
                    "total": total_count,
                })
    
    # Check sinusitis scenarios
    if results[0]["sinusitis_tests"]:
        for i in range(len(results[0]["sinusitis_tests"])):
            correct_count = sum(1 for r in results if r["sinusitis_tests"][i]["correct"])
            total_count = len(results)
            accuracy = correct_count / total_count if total_count > 0 else 0
            
            if accuracy < 0.5:
                scenario = results[0]["sinusitis_tests"][i]
                problematic.append({
                    "type": "Sinusitis",
                    "name": scenario["scenario_name"],
                    "expected": scenario["expected"],
                    "weighted_score": scenario["weighted_score"],
                    "accuracy": accuracy,
                    "correct": correct_count,
                    "total": total_count,
                })
    
    if problematic:
        # Sort by accuracy (ascending)
        problematic.sort(key=lambda x: x["accuracy"])
        
        print(f"\nFound {len(problematic)} problematic scenario(s):\n")
        for item in problematic:
            print(f"  • {item['type']}: {item['name']}")
            print(f"    Expected: {item['expected']} | Weighted Score: {item['weighted_score']:.3f}")
            print(f"    Success Rate: {item['accuracy']:.1%} ({item['correct']}/{item['total']} models)")
            print()
    else:
        print("\n✓ No problematic scenarios found (all scenarios have >50% success rate)")
    
    print("=" * 100)


def compare_best_vs_worst(results):
    """Compare the best and worst performing models."""
    if len(results) < 2:
        print("\nNeed at least 2 models to compare")
        return
    
    print("\n" + "=" * 100)
    print("BEST vs WORST MODEL COMPARISON")
    print("=" * 100)
    
    # Sort by overall accuracy
    results_sorted = sorted(results, key=lambda x: x["summary"]["overall_accuracy"], reverse=True)
    best = results_sorted[0]
    worst = results_sorted[-1]
    
    print(f"\nBest Model: {best['model']}")
    print(f"  Overall Accuracy: {best['summary']['overall_accuracy']:.1%}")
    print(f"  Migraine Accuracy: {best['summary']['migraine_accuracy']:.1%}")
    print(f"  Sinusitis Accuracy: {best['summary']['sinusitis_accuracy']:.1%}")
    
    print(f"\nWorst Model: {worst['model']}")
    print(f"  Overall Accuracy: {worst['summary']['overall_accuracy']:.1%}")
    print(f"  Migraine Accuracy: {worst['summary']['migraine_accuracy']:.1%}")
    print(f"  Sinusitis Accuracy: {worst['summary']['sinusitis_accuracy']:.1%}")
    
    # Find scenarios where best succeeded but worst failed
    print(f"\nScenarios where {best['model']} succeeded but {worst['model']} failed:")
    
    count = 0
    for i in range(len(best["migraine_tests"])):
        if best["migraine_tests"][i]["correct"] and not worst["migraine_tests"][i]["correct"]:
            scenario = best["migraine_tests"][i]
            print(f"  • Migraine: {scenario['scenario_name']}")
            print(f"    Expected: {scenario['expected']} | Best: {scenario['predicted']} | Worst: {worst['migraine_tests'][i]['predicted']}")
            count += 1
    
    for i in range(len(best["sinusitis_tests"])):
        if best["sinusitis_tests"][i]["correct"] and not worst["sinusitis_tests"][i]["correct"]:
            scenario = best["sinusitis_tests"][i]
            print(f"  • Sinusitis: {scenario['scenario_name']}")
            print(f"    Expected: {scenario['expected']} | Best: {scenario['predicted']} | Worst: {worst['sinusitis_tests'][i]['predicted']}")
            count += 1
    
    if count == 0:
        print("  (None - both models made the same mistakes)")
    
    print("\n" + "=" * 100)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Analyze LLM prediction test results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze all results
  python analyze_llm_results.py llm_results/*.json
  
  # Analyze specific models
  python analyze_llm_results.py llm_results/model1_*.json llm_results/model2_*.json
        """
    )
    
    parser.add_argument(
        "result_files",
        nargs="+",
        help="Path(s) to result JSON files"
    )
    
    args = parser.parse_args()
    
    # Load results
    print(f"Loading {len(args.result_files)} result file(s)...")
    results = load_results(args.result_files)
    
    if not results:
        print("ERROR: No valid result files found")
        sys.exit(1)
    
    print(f"Loaded {len(results)} result(s)")
    
    # Generate reports
    generate_summary_report(results)
    analyze_scenario_performance(results)
    identify_problematic_scenarios(results)
    
    if len(results) >= 2:
        compare_best_vs_worst(results)


if __name__ == "__main__":
    main()

