import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MonitorStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DOWN = "DOWN"
    PAUSED = "PAUSED"


class EventType(str, enum.Enum):
    MONITOR_CREATED = "MONITOR_CREATED"
    HEARTBEAT_RECEIVED = "HEARTBEAT_RECEIVED"
    ALERT_TRIGGERED = "ALERT_TRIGGERED"
    PAUSED = "PAUSED"
    RESUMED = "RESUMED"
    DELETED = "DELETED"
    RESTORED = "RESTORED"


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    timeout: Mapped[int] = mapped_column(Integer, nullable=False)
    alert_email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[MonitorStatus] = mapped_column(
        Enum(MonitorStatus, native_enum=False, length=20),
        nullable=False,
        default=MonitorStatus.ACTIVE,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    events: Mapped[list["MonitorEvent"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan", order_by="MonitorEvent.created_at"
    )


class MonitorEvent(Base):
    __tablename__ = "monitor_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, native_enum=False, length=30), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    monitor: Mapped["Monitor"] = relationship(back_populates="events")
