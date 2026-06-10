# Collapse prediction services into one deep module with a scoring-strategy seam

The migraine/sinusitis/hayfever prediction logic lived in a deep `BasePredictionService`
plus three subclasses. Two of them (migraine, sinusitis) were shallow config containers,
but hayfever carried real behavior (its own six-scorer pipeline plus a `predict()` override
that shadowed `self.WEIGHTS` and popped it in a `finally`). We collapsed the three services
into a single deep `PredictionService` (Interface: `predict()`), moved all per-condition
**data** into a `ConditionConfig` registry (`CONDITIONS`), and kept the **one** genuinely
varying axis — weather scoring — behind a narrow `ScoringStrategy` seam. Scoring returns a
`ScoreResult(scores, weights, factor_extras, confidence_factor)` so weight selection is an
output of scoring rather than mutable instance state.

## Considered Options

- **Free-function callable registry** — scoring as module-level functions referenced by data
  fields on `ConditionConfig`. Rejected: it scatters hayfever's six cohesive scorers into
  module scope, trading the leak for lost locality.
- **Scoring-strategy seam (chosen)** — `PredictionService` is one class; only scoring is
  polymorphic via three `ScoringStrategy` implementations. Honest about hayfever's real
  depth, keeps its scorers grouped, and still kills the call-site triplication.
- **Seal the hayfever leak only** — add a `_select_weights` seam to the base, leave the three
  subclasses. Rejected: removes the friction but not the shallowness of the migraine/sinusitis
  subclasses or the 5× threefold instantiation at call sites.

## Consequences

- Weight selection is no longer mutable instance state: hayfever's no-pollen swap is computed
  inside `ScoringStrategy.score()` and returned, eliminating the `self.WEIGHTS` shadow, the
  `finally`-pop, and the duplicate preview `WeatherForecast` query.
- `ScoreResult.confidence_factor` (hayfever's 0.75× no-pollen downgrade) is applied to the
  **recorded** LLM confidence **after** `_apply_confidence_threshold` runs — it must not feed
  into level classification, preserving the prior post-hoc annotation behavior.
- The per-condition wrappers (`predict_migraine_probability`, `predict_sinusitis_probability`,
  `predict_hayfever_probability`) are removed; all callers use `PredictionService.predict()`.
- Per-condition `THRESHOLDS`/`WEIGHTS` are no longer class attributes; consumers
  (e.g. `WeatherFactorExplainer`) read them via `CONDITIONS[type].scoring`.
