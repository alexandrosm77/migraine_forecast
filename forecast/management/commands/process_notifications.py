import logging

from django.utils import timezone
from sentry_sdk import add_breadcrumb, capture_exception, capture_message, set_context, set_tag, start_transaction

from forecast.management.commands.base import SilentStdoutCommand
from forecast.notification_intake import RUN_NORMAL, RUN_OVERRIDE_LIMITS, RUN_REPLAY, NotificationIntake

logger = logging.getLogger(__name__)


class Command(SilentStdoutCommand):
    help = "Process pending immediate notifications through NotificationIntake"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Build a full send plan without creating logs, sending email, or marking predictions",
        )
        parser.add_argument(
            "--replay",
            action="store_true",
            help="Bypass notification idempotency while still respecting preferences and rate limits",
        )
        parser.add_argument(
            "--override-limits",
            action="store_true",
            help="Bypass idempotency and rate limits while respecting hard email safety checks",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Deprecated alias for --replay",
        )
        parser.add_argument(
            "--lookback-hours",
            type=int,
            default=None,
            help="Override NotificationIntake's immediate discovery lookback window",
        )

    def handle(self, *args, **options):
        with start_transaction(op="cron.job", name="process_notifications"):
            set_tag("cron_job", "process_notifications")
            set_tag("task", "notification_processing")

            start_time = timezone.now()
            dry_run = options["dry_run"]
            run_mode = self._run_mode(options)
            self.stdout.write(self.style.SUCCESS(f"[{start_time}] Starting notification processing..."))
            if dry_run:
                self.stdout.write(self.style.WARNING("DRY RUN MODE - No notifications will be sent"))
                set_tag("dry_run", True)
            if options["force"]:
                self.stdout.write(self.style.WARNING("--force is deprecated; using replay mode"))

            add_breadcrumb(
                category="cron",
                message="Notification processing started",
                level="info",
                data={"start_time": str(start_time), "dry_run": dry_run, "run_mode": run_mode},
            )

            try:
                plan = NotificationIntake().run_immediate(
                    dry_run=dry_run,
                    run_mode=run_mode,
                    lookback_hours=options.get("lookback_hours"),
                )
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"\n✗ Error processing notifications: {exc}"))
                logger.error("Error processing notifications: %s", exc, exc_info=True)
                set_context("notification_processing_error", {"dry_run": dry_run, "run_mode": run_mode})
                capture_exception(exc)
                return

            self._write_plan(plan)
            self._write_summary(plan, start_time)

            add_breadcrumb(
                category="cron",
                message="Notification processing completed",
                level="info",
                data=plan.summary,
            )
            if not dry_run:
                capture_message(
                    f"Notification processing completed: {plan.summary.get('sent', 0)} notification(s) sent",
                    level="info",
                )

    def _run_mode(self, options):
        if options["override_limits"]:
            return RUN_OVERRIDE_LIMITS
        if options["replay"] or options["force"]:
            return RUN_REPLAY
        return RUN_NORMAL

    def _write_plan(self, plan):
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("NOTIFICATION SEND PLAN")
        self.stdout.write("=" * 60)
        if not plan.items:
            self.stdout.write(self.style.SUCCESS("No pending notifications to send"))
            return

        for item in plan.items:
            conditions = ", ".join(item.included_conditions)
            self.stdout.write(
                f"{item.user.username} ({item.user.email}) - {item.verdict.upper()} "
                f"[{conditions}] {item.predictions_count} prediction(s), {item.locations_count} location(s)"
            )
            if item.reason:
                self.stdout.write(f"  Reason: {item.reason}")

    def _write_summary(self, plan, start_time):
        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()
        by_condition = plan.summary.get("by_condition", {})
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("NOTIFICATION PROCESSING SUMMARY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Pending migraine predictions: {by_condition.get('migraine', 0)}")
        self.stdout.write(f"Pending sinusitis predictions: {by_condition.get('sinusitis', 0)}")
        self.stdout.write(f"Pending hay fever predictions: {by_condition.get('hayfever', 0)}")
        self.stdout.write(f"Users considered: {plan.summary.get('users_considered', 0)}")
        self.stdout.write(f"Would send: {plan.summary.get('send', 0)}")
        self.stdout.write(f"Notifications sent: {plan.summary.get('sent', 0)}")
        self.stdout.write(f"Skipped: {plan.summary.get('skipped', 0)}")
        self.stdout.write(f"Failed: {plan.summary.get('failed', 0)}")
        self.stdout.write(f"Duration: {duration:.2f} seconds")
        self.stdout.write(f"Completed at: {end_time}")
        self.stdout.write("=" * 60)
        logger.info(
            "Notification processing completed: summary=%s duration=%.2fs dry_run=%s run_mode=%s",
            plan.summary,
            duration,
            plan.dry_run,
            plan.run_mode,
        )
