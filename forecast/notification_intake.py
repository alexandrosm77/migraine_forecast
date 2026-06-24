import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.html import strip_tags
from sentry_sdk import capture_exception, capture_message

from .email_sender import EmailSender
from .models import HayFeverPrediction, MigrainePrediction, NotificationLog, SinusitisPrediction
from .notification_preferences import NotificationPreferences

logger = logging.getLogger(__name__)


CONDITIONS = {
    "migraine": {
        "model": MigrainePrediction,
        "enabled_attr": "migraine_predictions_enabled",
        "limit_attr": "daily_migraine_notification_limit",
        "m2m": "migraine_predictions",
    },
    "sinusitis": {
        "model": SinusitisPrediction,
        "enabled_attr": "sinusitis_predictions_enabled",
        "limit_attr": "daily_sinusitis_notification_limit",
        "m2m": "sinusitis_predictions",
    },
    "hayfever": {
        "model": HayFeverPrediction,
        "enabled_attr": "hay_fever_predictions_enabled",
        "limit_attr": "daily_hay_fever_notification_limit",
        "m2m": "hayfever_predictions",
    },
}

SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
RUN_NORMAL = "normal"
RUN_REPLAY = "replay"
RUN_OVERRIDE_LIMITS = "override_limits"


@dataclass
class NotificationPlanItem:
    user: object
    notification_type: str
    predictions: dict
    verdict: str
    reason: str = ""
    included_conditions: list = field(default_factory=list)
    limit_consumption: dict = field(default_factory=dict)
    locations_count: int = 0
    predictions_count: int = 0
    log_id: int | None = None
    run_mode: str = RUN_NORMAL


@dataclass
class NotificationSendPlan:
    dry_run: bool
    run_mode: str
    items: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    @property
    def sent_count(self):
        return self.summary.get("sent", 0)


class NotificationEmailAdapter:
    """Narrow email Adapter used by NotificationIntake."""

    def __init__(self):
        self._prefs = NotificationPreferences()

    def send_combined(self, user, predictions):
        location_data = EmailSender()._build_combined_location_data(
            predictions.get("migraine", []),
            predictions.get("sinusitis", []),
            predictions.get("hayfever", []),
        )
        context = self._combined_context(user, location_data)
        subject = self._combined_subject(location_data)
        self._send_rendered(user, subject, "forecast/email/combined_alert.html", context)
        return subject

    def send_digest(self, user, predictions):
        location_data = defaultdict(lambda: {"migraine": [], "sinusitis": [], "hayfever": []})
        for condition, preds in predictions.items():
            for pred in preds:
                location_data[pred.location.id]["location"] = pred.location
                location_data[pred.location.id][condition].append(pred)

        context = {
            "user": user,
            "location_data": list(location_data.values()),
            "migraine_count": len(predictions.get("migraine", [])),
            "sinusitis_count": len(predictions.get("sinusitis", [])),
            "hayfever_count": len(predictions.get("hayfever", [])),
            "total_count": sum(len(preds) for preds in predictions.values()),
            "digest_date": timezone.now().date(),
        }
        subject = f"Daily Health Digest - {len(location_data)} Location(s)"
        self._send_rendered(user, subject, "forecast/email/daily_digest.html", context)
        return subject

    def _combined_context(self, user, location_data):
        return {
            "user": user,
            "locations": location_data,
            "location_count": len(location_data),
            "has_migraine": any(loc.get("migraine_prediction") for loc in location_data),
            "has_sinusitis": any(loc.get("sinusitis_prediction") for loc in location_data),
            "has_hayfever": any(loc.get("hayfever_prediction") for loc in location_data),
            "first_migraine_tips": self._first_tip(location_data, "migraine_llm_prevention_tips"),
            "first_sinusitis_tips": self._first_tip(location_data, "sinusitis_llm_prevention_tips"),
            "first_hayfever_tips": self._first_tip(location_data, "hayfever_llm_prevention_tips"),
        }

    def _combined_subject(self, location_data):
        names = [loc["location"].city for loc in location_data]
        if len(names) == 1:
            location_str = names[0]
        elif len(names) == 2:
            location_str = f"{names[0]} & {names[1]}"
        else:
            location_str = f"{len(names)} locations"
        return f"Health Alert for {location_str}"

    def _send_rendered(self, user, subject, template, context):
        user_language = self._prefs.get_user_language(user)
        if user_language:
            translation.activate(user_language)
        try:
            html_message = render_to_string(template, context)
            plain_message = strip_tags(html_message)
        finally:
            translation.deactivate()

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )

    def _first_tip(self, location_data, key):
        for loc in location_data:
            if loc.get(key):
                return loc[key]
        return None


class NotificationIntake:
    """Deep Module for notification discovery, verdicts, sending, and finalization."""

    DEFAULT_IMMEDIATE_LOOKBACK_HOURS = 6

    def __init__(self, email_adapter=None):
        self.email_adapter = email_adapter or NotificationEmailAdapter()

    def run_immediate(self, dry_run=False, run_mode=RUN_NORMAL, lookback_hours=None):
        lookback_hours = lookback_hours or self.DEFAULT_IMMEDIATE_LOOKBACK_HOURS
        predictions_by_user = self._discover_immediate_predictions(lookback_hours, run_mode)
        return self._run_plan(predictions_by_user, "combined", dry_run, run_mode, is_digest=False)

    def send_digest(
        self,
        user,
        migraine_predictions=None,
        sinusitis_predictions=None,
        hayfever_predictions=None,
        dry_run=False,
        run_mode=RUN_NORMAL,
    ):
        predictions_by_user = {
            user: {
                "migraine": list(migraine_predictions or []),
                "sinusitis": list(sinusitis_predictions or []),
                "hayfever": list(hayfever_predictions or []),
            }
        }
        return self._run_plan(predictions_by_user, "digest", dry_run, run_mode, is_digest=True)

    def _discover_immediate_predictions(self, lookback_hours, run_mode):
        recent_time = timezone.now() - timedelta(hours=lookback_hours)
        by_user = defaultdict(lambda: {condition: [] for condition in CONDITIONS})

        for condition, config in CONDITIONS.items():
            query = (
                config["model"]
                .objects.filter(
                    prediction_time__gte=recent_time,
                    probability__in=["HIGH", "MEDIUM"],
                )
                .select_related("user", "location", "forecast")
            )
            if run_mode == RUN_NORMAL:
                query = query.filter(notification_sent=False).exclude(notification_logs__status="sent")

            for prediction in self._latest_per_location(query):
                by_user[prediction.user][condition].append(prediction)

        return {user: preds for user, preds in by_user.items() if self._prediction_count(preds)}

    def _latest_per_location(self, query):
        seen_location_ids = set()
        for prediction in query.order_by("location_id", "-prediction_time", "-id"):
            if prediction.location_id in seen_location_ids:
                continue
            seen_location_ids.add(prediction.location_id)
            yield prediction

    def _run_plan(self, predictions_by_user, notification_type, dry_run, run_mode, is_digest):
        plan = NotificationSendPlan(dry_run=dry_run, run_mode=run_mode)
        for user, predictions in predictions_by_user.items():
            if not self._prediction_count(predictions):
                continue
            item = self._build_item(user, notification_type, predictions, run_mode, is_digest)
            if item.verdict == "send" and not dry_run:
                self._send_item(item, is_digest)
            plan.items.append(item)
        plan.summary = self._summarize(plan.items)
        return plan

    def _build_item(self, user, notification_type, predictions, run_mode, is_digest):
        included_conditions = [condition for condition, preds in predictions.items() if preds]
        locations = {pred.location_id for preds in predictions.values() for pred in preds}
        item = NotificationPlanItem(
            user=user,
            notification_type=notification_type,
            predictions=predictions,
            verdict="send",
            included_conditions=included_conditions,
            limit_consumption=self._limit_consumption(included_conditions),
            locations_count=len(locations),
            predictions_count=self._prediction_count(predictions),
            run_mode=run_mode,
        )
        should_send, reason = self._verdict(user, predictions, included_conditions, run_mode, is_digest)
        if not should_send:
            item.verdict = "skip"
            item.reason = reason
        return item

    def _verdict(self, user, predictions, included_conditions, run_mode, is_digest):
        if not user.email:
            return False, "No email address"
        try:
            profile = user.health_profile
        except Exception:
            return True, "All checks passed"

        if not profile.email_notifications_enabled:
            return False, "Email notifications disabled"
        if not is_digest and profile.notification_mode == "DIGEST":
            return False, "User is in digest mode"
        for condition in included_conditions:
            if not getattr(profile, CONDITIONS[condition]["enabled_attr"], True):
                return False, f"{condition} predictions disabled"
        highest_severity = self._highest_severity(predictions)
        if not profile.should_send_notification(highest_severity):
            return False, f"Severity {highest_severity} below threshold"
        if profile.is_in_quiet_hours():
            return False, "User is in quiet hours"
        if run_mode == RUN_OVERRIDE_LIMITS:
            return True, "All checks passed"
        return self._rate_limit_verdict(user, profile, included_conditions)

    def _rate_limit_verdict(self, user, profile, included_conditions):
        start_of_day = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        sent_today = list(NotificationLog.objects.filter(user=user, status="sent", sent_at__gte=start_of_day))
        if profile.daily_notification_limit <= 0:
            return False, "Daily notifications disabled"
        if len(sent_today) >= profile.daily_notification_limit:
            return False, "Daily notification limit reached"

        condition_counts = self._condition_counts(sent_today)
        for condition in included_conditions:
            limit = getattr(profile, CONDITIONS[condition]["limit_attr"], 0)
            if limit > 0 and condition_counts[condition] >= limit:
                return False, f"{condition} daily notification limit reached"

        cutoff = timezone.now() - timedelta(hours=profile.notification_frequency_hours)
        if NotificationLog.objects.filter(user=user, status="sent", sent_at__gte=cutoff).exists():
            return False, "Notification frequency limit not met"
        return True, "All checks passed"

    def _send_item(self, item, is_digest):
        log = self._create_pending_log(item)
        item.log_id = log.id
        try:
            if is_digest:
                subject = self.email_adapter.send_digest(item.user, item.predictions)
            else:
                subject = self.email_adapter.send_combined(item.user, item.predictions)
        except Exception as exc:
            log.mark_failed(str(exc))
            item.verdict = "failed"
            item.reason = str(exc)
            capture_exception(exc)
            return

        try:
            with transaction.atomic():
                log.subject = subject
                log.save(update_fields=["subject", "updated_at"])
                log.mark_sent()
                self._mark_predictions_sent(item.predictions)
                self._update_last_notification_timestamps(item.user, item.included_conditions)
        except Exception as exc:
            item.verdict = "failed"
            item.reason = f"Email sent but finalization failed: {exc}"
            capture_exception(exc)
            capture_message("NotificationIntake finalization failed after email send", level="error")

    def _create_pending_log(self, item):
        severities = [pred.probability for preds in item.predictions.values() for pred in preds]
        highest = max(severities, key=lambda severity: SEVERITY_ORDER.get(severity, 0)) if severities else "LOW"
        log = NotificationLog.objects.create(
            user=item.user,
            notification_type=item.notification_type,
            status="pending",
            recipient=item.user.email,
            severity_level=highest,
            locations_count=item.locations_count,
            predictions_count=item.predictions_count,
            metadata={
                "included_conditions": item.included_conditions,
                "limit_consumption": item.limit_consumption,
                "run_mode": item.run_mode,
                "module": "NotificationIntake",
            },
        )
        for condition, predictions in item.predictions.items():
            getattr(log, CONDITIONS[condition]["m2m"]).set(predictions)
        return log

    def _mark_predictions_sent(self, predictions):
        for condition, preds in predictions.items():
            for prediction in preds:
                prediction.notification_sent = True
                prediction.save(update_fields=["notification_sent"])

    def _update_last_notification_timestamps(self, user, included_conditions):
        try:
            profile = user.health_profile
        except Exception as exc:
            logger.warning("Could not update last notification timestamp for user %s: %s", user.username, exc)
            return

        now = timezone.now()
        profile.last_notification_sent_at = now
        if "migraine" in included_conditions:
            profile.last_migraine_notification_sent_at = now
        if "sinusitis" in included_conditions:
            profile.last_sinusitis_notification_sent_at = now
        if "hayfever" in included_conditions:
            profile.last_hay_fever_notification_sent_at = now
        profile.save()

    def _condition_counts(self, logs):
        counts = {condition: 0 for condition in CONDITIONS}
        for log in logs:
            metadata_conditions = (log.metadata or {}).get("included_conditions") or []
            if metadata_conditions:
                for condition in set(metadata_conditions):
                    if condition in counts:
                        counts[condition] += 1
                continue
            if log.notification_type in counts:
                counts[log.notification_type] += 1
            for condition, config in CONDITIONS.items():
                if getattr(log, config["m2m"]).exists():
                    counts[condition] += 1
        return counts

    def _limit_consumption(self, included_conditions):
        return {"overall": 1, **{condition: 1 for condition in included_conditions}}

    def _highest_severity(self, predictions):
        severities = [pred.probability for preds in predictions.values() for pred in preds]
        return max(severities, key=lambda severity: SEVERITY_ORDER.get(severity, 0)) if severities else "LOW"

    def _prediction_count(self, predictions):
        return sum(len(preds) for preds in predictions.values())

    def _summarize(self, items):
        summary = {
            "users_considered": len(items),
            "send": sum(1 for item in items if item.verdict == "send"),
            "sent": sum(1 for item in items if item.verdict == "send" and item.log_id),
            "skipped": sum(1 for item in items if item.verdict == "skip"),
            "failed": sum(1 for item in items if item.verdict == "failed"),
            "predictions": sum(item.predictions_count for item in items),
            "by_condition": {condition: 0 for condition in CONDITIONS},
            "skip_reasons": defaultdict(int),
        }
        for item in items:
            for condition in item.included_conditions:
                summary["by_condition"][condition] += len(item.predictions.get(condition, []))
            if item.verdict == "skip":
                summary["skip_reasons"][item.reason] += 1
        summary["skip_reasons"] = dict(summary["skip_reasons"])
        return summary
