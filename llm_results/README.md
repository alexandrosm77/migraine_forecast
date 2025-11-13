# LLM Test Results

This directory contains test results from the LLM prediction test suite.

## Directory Structure

```
llm_results/
├── README.md                           # This file
├── <model-name>_<timestamp>.json       # Individual test results
└── ...
```

## Result File Format

Each JSON file contains:

```json
{
  "model": "model-name",
  "base_url": "http://localhost:1234",
  "timestamp": "2025-11-09T21:00:00",
  "migraine_tests": [
    {
      "scenario_name": "Clear LOW - Minimal risk",
      "description": "Perfect weather, no risk factors",
      "weighted_score": 0.0,
      "expected": "LOW",
      "predicted": "LOW",
      "correct": true,
      "confidence": 0.95,
      "rationale": "...",
      "analysis": "...",
      "error": null
    },
    ...
  ],
  "sinusitis_tests": [...],
  "summary": {
    "migraine_accuracy": 0.875,
    "migraine_correct": 7,
    "migraine_total": 8,
    "migraine_errors": 0,
    "sinusitis_accuracy": 1.0,
    "sinusitis_correct": 3,
    "sinusitis_total": 3,
    "sinusitis_errors": 0,
    "overall_accuracy": 0.909,
    "total_correct": 10,
    "total_tests": 11,
    "total_errors": 0
  }
}
```

## Test Scenarios

### Migraine Tests (8 scenarios)

1. **Clear LOW** - Minimal risk (all factors = 0)
2. **Clear HIGH** - Multiple severe factors (weighted score ~0.88)
3. **Boundary MEDIUM (low end)** - Just above LOW threshold (score ~0.42)
4. **Boundary MEDIUM (high end)** - Just below HIGH threshold (score ~0.71)
5. **Boundary HIGH (low end)** - Just at HIGH threshold (score ~0.77)
6. **High pressure change only** - Single dominant factor
7. **London example** - Real-world case (score ~0.47, should be MEDIUM)
8. **Thessaloniki example** - Real-world case (score ~0.38, should be LOW)

### Sinusitis Tests (3 scenarios)

1. **Clear LOW** - Minimal risk
2. **Clear HIGH** - High humidity + temperature change (score ~0.81)
3. **Boundary MEDIUM** - Just above LOW threshold (score ~0.37)

## Classification Thresholds

### Migraine (default sensitivity_overall = 1.0)
- **LOW**: weighted_score < 0.4
- **MEDIUM**: 0.4 ≤ weighted_score < 0.7
- **HIGH**: weighted_score ≥ 0.7

### Sinusitis (default sensitivity_overall = 1.0)
- **LOW**: weighted_score < 0.35
- **MEDIUM**: 0.35 ≤ weighted_score < 0.65
- **HIGH**: weighted_score ≥ 0.65

**Note**: Thresholds are adjusted based on user `sensitivity_overall`:
- shift = (sensitivity_overall - 1.0) × 0.15
- Higher sensitivity → lower thresholds (more predictions are MEDIUM/HIGH)
- Lower sensitivity → higher thresholds (more predictions are LOW/MEDIUM)

## Interpreting Results

### Accuracy Metrics

- **≥90%**: Excellent - Model is highly reliable
- **75-89%**: Good - Model is generally reliable with some edge case issues
- **60-74%**: Fair - Model needs improvement, may have systematic biases
- **<60%**: Poor - Model is not suitable for production use

### Common Issues to Look For

1. **Boundary confusion**: Model struggles with scores near thresholds (0.4, 0.7)
2. **Over-prediction**: Model consistently predicts higher severity than expected
3. **Under-prediction**: Model consistently predicts lower severity than expected
4. **Single-factor bias**: Model over-weights individual high factors vs. weighted score
5. **Inconsistency**: Model gives different predictions for similar scenarios

## Comparing Models

Use the analysis script to compare multiple models:

```bash
python analyze_llm_results.py llm_results/*.json
```

This will show:
- Overall accuracy ranking
- Per-scenario performance across all models
- Problematic scenarios (low success rate)
- Best vs worst model comparison

## Best Practices

1. **Test new models** before deploying to production
2. **Compare models** to find the best performer for your use case
3. **Monitor edge cases** - boundary scenarios are most likely to fail
4. **Check real-world examples** - London and Thessaloniki scenarios are based on actual misclassifications
5. **Consider cost vs accuracy** - Smaller local models may be "good enough" vs expensive API calls

## Model Selection Criteria

When choosing a model, consider:

1. **Accuracy**: Overall and per-scenario performance
2. **Consistency**: Low variance in predictions for similar scenarios
3. **Cost**: API costs vs local hosting
4. **Speed**: Response time for predictions
5. **Reliability**: Error rate and availability
6. **Explainability**: Quality of rationale and analysis text

## Troubleshooting

### All predictions are HIGH
- Model is ignoring weighted score
- Model is over-weighting individual factors
- Check system prompt is being sent correctly

### All predictions are LOW
- Model is being too conservative
- Model may not understand the scoring system
- Check threshold values in prompt

### Random/inconsistent predictions
- Model temperature may be too high (should be 0.2)
- Model may be too small/weak for the task
- Try a larger or more capable model

### Errors in results
- Check LLM server is running and accessible
- Verify API key if using cloud service
- Check timeout settings (increase if needed)
- Review logs for connection issues

