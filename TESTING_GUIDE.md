# LLM Testing Guide

This guide explains how to use the manual LLM testing tools to evaluate and compare different models for migraine and sinusitis predictions.

## Overview

The testing suite consists of:

1. **`run_llm_tests.py`** - Main test runner that evaluates LLM performance (manual execution only)
2. **`analyze_llm_results.py`** - Analysis tool for comparing results across models
3. **`llm_results/`** - Directory where test results are stored

**Note**: The test runner is named `run_llm_tests.py` (not `test_*.py`) to prevent pytest from automatically discovering and running it. These tests are designed for manual execution only.

## Quick Start

### 1. Run Tests with Current LLM Configuration

```bash
# Test using the LLM configured in the database
python run_llm_tests.py
```

This will:
- Load the active LLM configuration from the database
- Run 8 migraine scenarios and 3 sinusitis scenarios
- Display results in real-time
- Save results to `llm_results/<model-name>_<timestamp>.json`
- Show overall accuracy and performance rating

### 2. Test a Specific Model

```bash
# Test a local model
python run_llm_tests.py --model "granite-4.0-h-tiny-mlx" --base-url "http://localhost:1234"

# Test an OpenAI model
python run_llm_tests.py --model "gpt-4o-mini" --base-url "https://api.openai.com/v1" --api-key "sk-..."

# Test with custom timeout (for slower models)
python run_llm_tests.py --model "llama-3.2-1b" --timeout 300
```

### 3. Analyze Results

```bash
# Analyze all test results
python analyze_llm_results.py llm_results/*.json

# Compare specific models
python analyze_llm_results.py llm_results/granite*.json llm_results/gpt*.json
```

## Test Scenarios

### Migraine Tests (8 scenarios)

| Scenario | Weighted Score | Expected | Description |
|----------|---------------|----------|-------------|
| Clear LOW | 0.00 | LOW | Perfect weather, no risk factors |
| Clear HIGH | 0.88 | HIGH | Multiple severe factors |
| Boundary MEDIUM (low) | 0.42 | MEDIUM | Just above LOW threshold |
| Boundary MEDIUM (high) | 0.71 | HIGH | Just at HIGH threshold |
| Boundary HIGH | 0.77 | HIGH | Clearly HIGH |
| High pressure only | 0.39 | LOW | Single dominant factor |
| **London example** | 0.47 | MEDIUM | Real-world misclassification |
| **Thessaloniki example** | 0.38 | LOW | Real-world misclassification |

### Sinusitis Tests (3 scenarios)

| Scenario | Weighted Score | Expected | Description |
|----------|---------------|----------|-------------|
| Clear LOW | 0.00 | LOW | Perfect weather |
| Clear HIGH | 0.81 | HIGH | High humidity + temp change |
| Boundary MEDIUM | 0.37 | MEDIUM | Just above LOW threshold |

## Understanding Results

### Accuracy Ratings

- **≥90% - EXCELLENT**: Model is production-ready
- **75-89% - GOOD**: Model is reliable with minor issues
- **60-74% - FAIR**: Model needs improvement
- **<60% - POOR**: Model not suitable for production

### Common Issues

1. **Boundary Confusion**: Model struggles with scores near thresholds (0.4, 0.7)
   - Example: London scenario (0.47) should be MEDIUM but predicted as LOW

2. **Over-prediction**: Model predicts higher severity than expected
   - Check if model is ignoring weighted score
   - May be over-weighting individual high factors

3. **Under-prediction**: Model predicts lower severity than expected
   - Model may be too conservative
   - Check if thresholds are being communicated correctly

## Comparing Models

### Example Workflow

```bash
# Test Model A (local)
python run_llm_tests.py --model "granite-4.0-h-tiny-mlx"

# Test Model B (OpenAI)
python run_llm_tests.py --model "gpt-4o-mini" --api-key "sk-..."

# Test Model C (Anthropic)
python run_llm_tests.py --model "claude-3-haiku" --base-url "https://api.anthropic.com/v1" --api-key "sk-ant-..."

# Compare all results
python analyze_llm_results.py llm_results/*.json
```

### What to Look For

1. **Overall Accuracy**: Which model gets the most scenarios correct?
2. **Boundary Performance**: Which model handles edge cases best?
3. **Consistency**: Does the model give similar predictions for similar scenarios?
4. **Real-World Cases**: Does it correctly classify London and Thessaloniki examples?
5. **Cost vs Performance**: Is a more expensive model worth the accuracy gain?

## Advanced Usage

### Testing with User Sensitivity

The test suite currently uses default sensitivity (1.0). To test with different sensitivity levels, you would need to modify the test scenarios in `test_llm_predictions.py`.

### Adding New Scenarios

Edit `run_llm_tests.py` and add to `MIGRAINE_TEST_SCENARIOS` or `SINUSITIS_TEST_SCENARIOS`:

```python
{
    "name": "My Custom Scenario",
    "description": "Description of the scenario",
    "expected": "MEDIUM",  # or "LOW" or "HIGH"
    "scores": {
        "temperature_change": 0.5,
        "humidity_extreme": 0.6,
        "pressure_change": 0.4,
        "pressure_low": 0.3,
        "precipitation": 0.2,
        "cloud_cover": 0.5,
    },
    "context": {
        "aggregates": {
            "avg_forecast_temperature": 15.0,
            "avg_forecast_humidity": 75.0,
            "avg_forecast_pressure": 1005.0,
        }
    }
}
```

### Skipping Result Saving

```bash
# Run tests without saving results (for quick testing)
python run_llm_tests.py --no-save
```

## Interpreting Analysis Output

### Summary Report

Shows all models ranked by overall accuracy:

```
Rank   Model                    Timestamp            Overall      Migraine     Sinusitis   
1      granite-4.0-h-tiny-mlx   2025-11-09T22:13:44  90.9% (10/11) 87.5% (7/8)  100.0% (3/3)
2      gpt-4o-mini              2025-11-09T22:30:00  100.0% (11/11) 100.0% (8/8) 100.0% (3/3)
```

### Scenario-Level Analysis

Shows how each scenario performed across all models:

```
7. London example (reported as HIGH)
   Expected: MEDIUM | Weighted Score: 0.468
   Accuracy: 50.0% (1/2 models correct)
   Predictions: {'LOW': 1, 'MEDIUM': 1}
   Failed by: granite-4.0-h-tiny-mlx
```

### Problematic Scenarios

Lists scenarios where <50% of models got it right:

```
Found 1 problematic scenario(s):

  • Migraine: London example (reported as HIGH)
    Expected: MEDIUM | Weighted Score: 0.468
    Success Rate: 0.0% (1/1 models)
```

### Best vs Worst Comparison

Shows specific scenarios where the best model succeeded but worst failed.

## Troubleshooting

### Connection Errors

```
ERROR: HTTPConnectionPool(host='localhost', port=1234): Max retries exceeded
```

**Solution**: Make sure your LLM server is running:
- For local models: Check that LM Studio or similar is running on the specified port
- For API models: Verify the base URL and API key are correct

### Timeout Errors

```
ERROR: Request timeout after 120 seconds
```

**Solution**: Increase timeout for slower models:
```bash
python run_llm_tests.py --timeout 300
```

### Invalid JSON Responses

```
WARNING: LLM response not JSON parsable
```

**Solution**: 
- Model may be too small/weak for the task
- Try a larger or more capable model
- Check that the model supports JSON output

### All Predictions Wrong

**Possible causes**:
1. Model is not following the system prompt
2. Weights or thresholds are incorrect in the prompt
3. Model is too small for the task

**Solution**: Review the logged requests to see what the model received, and try a more capable model.

## Best Practices

1. **Test before deploying**: Always test a new model before using it in production
2. **Test multiple models**: Compare at least 2-3 models to find the best fit
3. **Monitor edge cases**: Pay special attention to boundary scenarios
4. **Check real-world examples**: London and Thessaloniki scenarios are based on actual issues
5. **Consider cost**: Balance accuracy against API costs or local hosting requirements
6. **Re-test periodically**: Model behavior can change with updates
7. **Save all results**: Keep a history of test results for comparison

## Example Session

```bash
# 1. Test current model
$ python run_llm_tests.py
Using LLM configuration from database:
  Model: granite-4.0-h-tiny-mlx
  Base URL: http://localhost:1234
...
Overall Accuracy: 90.9% (10/11)
✓ EXCELLENT: Model performance is excellent (≥90% accuracy)

# 2. Test alternative model
$ python run_llm_tests.py --model "gpt-4o-mini" --api-key "sk-..."
...
Overall Accuracy: 100.0% (11/11)
✓ EXCELLENT: Model performance is excellent (≥90% accuracy)

# 3. Compare results
$ python analyze_llm_results.py llm_results/*.json
...
Rank   Model                    Overall
1      gpt-4o-mini              100.0% (11/11)
2      granite-4.0-h-tiny-mlx   90.9% (10/11)

# 4. Decision: gpt-4o-mini is more accurate but costs money
#    granite-4.0-h-tiny-mlx is free (local) and "good enough" at 90.9%
```

## Next Steps

After testing:

1. **Choose the best model** based on accuracy, cost, and speed
2. **Update LLM configuration** in the Django admin
3. **Monitor production predictions** to ensure real-world performance matches tests
4. **Re-run tests** if you notice issues in production
5. **Add new scenarios** based on real-world misclassifications

