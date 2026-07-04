import json
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.db.database import SessionLocal
from app.repositories.monitor_repository import MonitorRepository
from app.services.monitor_service import MonitorService

logger = logging.getLogger("pulse_check.scheduler")

_scheduler = None

# Overridable so tests (or alternate deployments) can point the scheduler at a
# different engine/session without touching the app's default SessionLocal.
_session_factory = SessionLocal


def check_expired_monitors() -> None:
    """Runs on every scheduler tick. Loads all ACTIVE monitors, and for any
    whose timeout has elapsed since the last heartbeat, transitions them to
    DOWN and fires the alert."""
    db = _session_factory()
    try:
        service = MonitorService(db)
        repo = MonitorRepository(db)

        for monitor in repo.list_active():
            went_down = service.mark_down_if_expired(monitor)
            if went_down:
                fire_alert(monitor.device_id)
    except Exception:
        logger.exception("Error while checking expired monitors")
    finally:
        db.close()


def purge_expired_deleted_monitors() -> None:
    """Runs periodically (default: daily). Permanently removes soft-deleted
    monitors whose retention period has elapsed."""
    db = _session_factory()
    try:
        service = MonitorService(db)
        purged = service.purge_expired_deleted_monitors(settings.retention_period_days)
        if purged:
            logger.info("Purged %d expired soft-deleted monitor(s): %s", len(purged), purged)
    except Exception:
        logger.exception("Error while purging expired deleted monitors")
    finally:
        db.close()


def fire_alert(device_id: str) -> None:
    """Simulated alert delivery. In production this would send an email/webhook;
    here we log the structured payload the spec asks for."""
    alert = {
        "ALERT": f"Device {device_id} is down!",
        "time": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(alert))
    logger.warning("ALERT_TRIGGERED %s", json.dumps(alert))


def start_scheduler(session_factory=None) -> BackgroundScheduler:
    """Creates a fresh scheduler instance if none is running. APScheduler's
    shutdown() permanently kills its executor, so a previously-shutdown
    instance can never be restarted -- we must build a new one each time."""
    global _scheduler, _session_factory
    if session_factory is not None:
        _session_factory = session_factory

    if _scheduler is None or not _scheduler.running:
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(
            check_expired_monitors,
            "interval",
            seconds=settings.scheduler_interval_seconds,
            id="check_expired_monitors",
            replace_existing=True,
            max_instances=1,
        )
        _scheduler.add_job(
            purge_expired_deleted_monitors,
            "interval",
            hours=settings.purge_interval_hours,
            id="purge_expired_deleted_monitors",
            replace_existing=True,
            max_instances=1,
        )
        _scheduler.start()
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
