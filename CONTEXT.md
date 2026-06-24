# Domain context

This file records project vocabulary that should guide architecture reviews and refactors.

## Notification domain

### Notification intake

The domain operation that starts from persisted predictions and decides what, if anything, should be sent to a user. Immediate notification intake starts at the database: callers should not build condition-specific prediction dictionaries or know the pending-prediction query rules.

The deep Module for this operation is named `NotificationIntake`. It owns discovery, grouping, notification verdicts, sending/logging, and finalization; runtime entry points such as management commands, Celery tasks, and admin actions are Adapters over it.

### Notification verdict

The decision for a candidate notification: send, skip, or fail, with the reason. Verdicts account for email availability, email notification settings, notification mode, quiet hours, severity threshold, daily limits, per-condition daily limits, frequency limits, and idempotency.

### Notification ledger

`NotificationLog` is the canonical ledger for notification verdicts, sent/skipped/failed audit, daily limits, per-condition daily limits, and frequency checks.

Prediction rows may keep `notification_sent` as a denormalized sent index for compatibility and fast filtering, but it is not the canonical ledger.

### Immediate notification

A notification run for recent HIGH/MEDIUM migraine, sinusitis, or hay fever predictions. The notification Module owns immediate pending prediction discovery, grouping, verdicts, sending/logging, and marking sent.

### Digest notification

A scheduled email for users in DIGEST mode. Digest prediction generation and digest schedule timing are outside the notification Module. Once digest predictions exist, digest sending, verdicts, logging, and marking sent use the notification Module.

### Combined notification limit consumption

A combined notification consumes one overall daily notification slot, plus one per-condition daily slot for each included condition, regardless of how many Locations or predictions are included for that condition.

Example: a combined email with three migraine predictions and one hay fever prediction consumes overall +1, migraine +1, sinusitis +0, and hay fever +1.

`NotificationLog.metadata` should record the included conditions and computed limit consumption for the notification. Many-to-many links to predictions remain audit/details links, not the only source for limit-consumption policy.

### Notification idempotency

During the notification intake refactor, a prediction is eligible only if it is not linked to any sent `NotificationLog` and its prediction row has `notification_sent=False`. This uses both the canonical ledger and the denormalized sent index for safe transition.

### Replay mode

A run mode that bypasses idempotency only. It may reconsider predictions already marked or logged as sent, while still respecting user notification preferences and rate limits.

### Override limits mode

A run mode that bypasses idempotency and rate limits for explicit operator action. It should still respect hard safety checks such as missing email addresses and email notifications being disabled.

### Dry run

A no-write notification intake run. It performs full pending prediction discovery, grouping, notification verdicts, and limit-consumption planning, then returns a send plan with send/skip reasons. It must not create `NotificationLog` rows, send email, or mark predictions as sent.
