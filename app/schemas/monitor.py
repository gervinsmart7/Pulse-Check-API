import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.monitor import EventType, MonitorStatus


class MonitorCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=255, description="Device identifier")
    timeout: int = Field(..., gt=0, description="Seconds before the monitor is considered down")
    alert_email: EmailStr


class MonitorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str = Field(validation_alias="device_id")
    timeout: int
    alert_email: str
    status: MonitorStatus
    last_heartbeat: datetime
    created_at: datetime
    updated_at: datetime


class MonitorCreatedResponse(BaseModel):
    message: str
    monitor: MonitorResponse


class MonitorEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: EventType
    message: str
    created_at: datetime

class GlobalMonitorEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: str
    event_type: EventType
    message: str
    created_at: datetime

class ErrorResponse(BaseModel):
    detail: str
