import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monitor import EventType, Monitor, MonitorEvent, MonitorStatus


class MonitorRepository:
    """Encapsulates all direct database access for monitors and their events.
    No business logic lives here -- just persistence."""

    def __init__(self, db: Session):
        self.db = db

    # -- Monitors ---------------------------------------------------------

    def get_by_device_id(self, device_id: str, include_deleted: bool = False) -> Optional[Monitor]:
        stmt = select(Monitor).where(Monitor.device_id == device_id)
        if not include_deleted:
            stmt = stmt.where(Monitor.is_deleted.is_(False))
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id(self, monitor_id: uuid.UUID) -> Optional[Monitor]:
        return self.db.get(Monitor, monitor_id)

    def list_all(self) -> list[Monitor]:
        stmt = (
            select(Monitor)
            .where(Monitor.is_deleted.is_(False))
            .order_by(Monitor.created_at)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_active(self) -> list[Monitor]:
        stmt = select(Monitor).where(
            Monitor.status == MonitorStatus.ACTIVE, Monitor.is_deleted.is_(False)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_deleted_before(self, cutoff: datetime) -> list[Monitor]:
        stmt = select(Monitor).where(
            Monitor.is_deleted.is_(True), Monitor.deleted_at <= cutoff
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(self, monitor: Monitor) -> Monitor:
        self.db.add(monitor)
        self.db.flush()
        return monitor

    def soft_delete(self, monitor: Monitor, deleted_at: datetime) -> None:
        monitor.is_deleted = True
        monitor.deleted_at = deleted_at

    def hard_delete(self, monitor: Monitor) -> None:
        self.db.delete(monitor)

    # -- Events -------------------------------------------------------------

    def add_event(self, monitor_id: uuid.UUID, event_type: EventType, message: str) -> MonitorEvent:
        event = MonitorEvent(monitor_id=monitor_id, event_type=event_type, message=message)
        self.db.add(event)
        self.db.flush()
        return event

    def list_events(self, monitor_id: uuid.UUID) -> list[MonitorEvent]:
        stmt = (
            select(MonitorEvent)
            .where(MonitorEvent.monitor_id == monitor_id)
            .order_by(MonitorEvent.created_at)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_all_events(
        self,
        event_type: Optional[EventType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[MonitorEvent, str]]:
        """Returns (event, device_id) pairs across ALL monitors (including
        soft-deleted ones, since purged history is a separate concern),
        newest first, optionally filtered by device_id and/or event_type."""
        stmt = (
            select(MonitorEvent, Monitor.device_id)
            .join(Monitor, MonitorEvent.monitor_id == Monitor.id)
            .order_by(MonitorEvent.created_at.desc())
        )
        if event_type is not None:
            stmt = stmt.where(MonitorEvent.event_type == event_type)
        stmt = stmt.limit(limit).offset(offset)

        return [(row[0], row[1]) for row in self.db.execute(stmt).all()]

    # -- Transaction helpers --------------------------------------------------

    def commit(self) -> None:
        self.db.commit()

    def refresh(self, monitor: Monitor) -> None:
        self.db.refresh(monitor)
