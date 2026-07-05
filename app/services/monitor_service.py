import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.monitor import EventType, Monitor, MonitorStatus
from app.repositories.monitor_repository import MonitorRepository
from app.schemas.monitor import MonitorCreate


class DuplicateMonitorError(Exception):
    """Raised when a monitor with the given device_id already exists."""


class MonitorNotFoundError(Exception):
    """Raised when a monitor cannot be located by device_id."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MonitorService:
    """Implements the Dead Man's Switch state machine:

        NONE   --Register--> ACTIVE
        ACTIVE --Heartbeat--> ACTIVE
        ACTIVE --Timeout-->   DOWN
        ACTIVE --Pause-->     PAUSED
        PAUSED --Heartbeat--> ACTIVE

    Deletion is a soft delete: the monitor is hidden from normal listing/
    lookup and can no longer receive heartbeats/pauses, but its row and full
    event history remain in the database for a retention period so
    administrators can review the audit trail. After that period expires,
    a background job permanently purges it.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = MonitorRepository(db)

    def register(self, payload: MonitorCreate) -> Monitor:
        if self.repo.get_by_device_id(payload.id):
            raise DuplicateMonitorError(f"Monitor '{payload.id}' already exists")

        monitor = Monitor(
            device_id=payload.id,
            timeout=payload.timeout,
            alert_email=payload.alert_email,
            status=MonitorStatus.ACTIVE,
            last_heartbeat=utcnow(),
        )
        self.repo.create(monitor)
        self.repo.add_event(
            monitor.id,
            EventType.MONITOR_CREATED,
            f"Monitor created for device '{monitor.device_id}' with {monitor.timeout}s timeout",
        )
        self.repo.commit()
        self.repo.refresh(monitor)
        return monitor

    def heartbeat(self, device_id: str) -> Monitor:
        monitor = self.repo.get_by_device_id(device_id)
        if monitor is None:
            raise MonitorNotFoundError(f"Monitor '{device_id}' not found")

        was_paused = monitor.status == MonitorStatus.PAUSED

        monitor.status = MonitorStatus.ACTIVE
        monitor.last_heartbeat = utcnow()

        if was_paused:
            self.repo.add_event(
                monitor.id, EventType.RESUMED, f"Monitoring resumed for '{device_id}' via heartbeat"
            )

        self.repo.add_event(
            monitor.id, EventType.HEARTBEAT_RECEIVED, f"Heartbeat received for '{device_id}'"
        )
        self.repo.commit()
        self.repo.refresh(monitor)
        return monitor

    def pause(self, device_id: str) -> Monitor:
        monitor = self.repo.get_by_device_id(device_id)
        if monitor is None:
            raise MonitorNotFoundError(f"Monitor '{device_id}' not found")

        monitor.status = MonitorStatus.PAUSED
        self.repo.add_event(
            monitor.id, EventType.PAUSED, f"Monitoring paused for '{device_id}'"
        )
        self.repo.commit()
        self.repo.refresh(monitor)
        return monitor

    def get(self, device_id: str) -> Monitor:
        monitor = self.repo.get_by_device_id(device_id)
        if monitor is None:
            raise MonitorNotFoundError(f"Monitor '{device_id}' not found")
        return monitor

    def list_all(self) -> list[Monitor]:
        return self.repo.list_all()

    def history(self, device_id: str):
        """Returns event history even for soft-deleted monitors (until they
        are permanently purged after the retention period)."""
        monitor = self.repo.get_by_device_id(device_id, include_deleted=True)
        if monitor is None:
            raise MonitorNotFoundError(f"Monitor '{device_id}' not found")
        return self.repo.list_events(monitor.id)

    def delete(self, device_id: str) -> None:
        monitor = self.get(device_id)
        now = utcnow()
        self.repo.soft_delete(monitor, deleted_at=now)
        self.repo.add_event(
            monitor.id, EventType.DELETED, f"Monitor '{device_id}' deleted"
        )
        self.repo.commit()

    def restore(self, device_id: str) -> Monitor:
        """Reverses a soft delete. Only works for monitors that are actually
        soft-deleted and haven't yet been permanently purged (once the
        retention period expires and the purge job runs, the row is gone
        for real -- there is nothing left to restore)."""
        monitor = self.repo.get_by_device_id(device_id, include_deleted=True)
        if monitor is None:
            raise MonitorNotFoundError(f"Monitor '{device_id}' not found")
        if not monitor.is_deleted:
            raise MonitorNotFoundError(
                f"Monitor '{device_id}' is not deleted, nothing to restore"
            )

        self.repo.restore(monitor)
        self.repo.add_event(
            monitor.id, EventType.RESTORED, f"Monitor '{device_id}' restored from deletion"
        )
        self.repo.commit()
        self.repo.refresh(monitor)
        return monitor

    # -- Called by the scheduler, not the API layer -----------------------

    def mark_down_if_expired(self, monitor: Monitor) -> bool:
        """Returns True if this monitor was just transitioned to DOWN."""
        elapsed = (utcnow() - monitor.last_heartbeat.replace(tzinfo=timezone.utc)).total_seconds()
        if elapsed < monitor.timeout:
            return False

        monitor.status = MonitorStatus.DOWN
        self.repo.add_event(
            monitor.id,
            EventType.ALERT_TRIGGERED,
            f"Device '{monitor.device_id}' missed its {monitor.timeout}s heartbeat window",
        )
        self.repo.commit()
        return True


    def list_all_events(
        self,
        event_type: EventType | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        """Global, filterable event log across every monitor -- for admins
        who want to search/browse the whole audit trail, not just one
        device's history."""
        return self.repo.list_all_events(
            event_type=event_type, limit=limit, offset=offset
        )

    def purge_expired_deleted_monitors(self, retention_period_days: int) -> list[str]:
        """Permanently removes soft-deleted monitors (and their events, via
        cascade) whose retention window has elapsed. Returns the device_ids
        that were purged, for logging."""
        cutoff = utcnow() - timedelta(days=retention_period_days)
        expired = self.repo.list_deleted_before(cutoff)
        purged_ids = [m.device_id for m in expired]

        for monitor in expired:
            self.repo.hard_delete(monitor)

        if purged_ids:
            self.repo.commit()
        return purged_ids
