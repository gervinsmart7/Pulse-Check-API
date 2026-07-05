from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.monitor import (
    GlobalMonitorEventResponse,
    MonitorCreate,
    MonitorCreatedResponse,
    MonitorEventResponse,
    MonitorResponse,
)
from app.models.monitor import EventType
from app.services.monitor_service import (
    DuplicateMonitorError,
    MonitorNotFoundError,
    MonitorService,
)

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.post("", response_model=MonitorCreatedResponse, status_code=status.HTTP_201_CREATED)
def register_monitor(payload: MonitorCreate, db: Session = Depends(get_db)):
    service = MonitorService(db)
    try:
        monitor = service.register(payload)
    except DuplicateMonitorError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return MonitorCreatedResponse(
        message=f"Monitor '{monitor.device_id}' registered successfully",
        monitor=MonitorResponse.model_validate(monitor),
    )


@router.get("", response_model=list[MonitorResponse])
def list_monitors(db: Session = Depends(get_db)):
    service = MonitorService(db)
    return [MonitorResponse.model_validate(m) for m in service.list_all()]


@router.get("/{device_id}", response_model=MonitorResponse)
def get_monitor(device_id: str, db: Session = Depends(get_db)):
    service = MonitorService(db)
    try:
        monitor = service.get(device_id)
    except MonitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return MonitorResponse.model_validate(monitor)


@router.post("/{device_id}/heartbeat", response_model=MonitorResponse)
def send_heartbeat(device_id: str, db: Session = Depends(get_db)):
    service = MonitorService(db)
    try:
        monitor = service.heartbeat(device_id)
    except MonitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return MonitorResponse.model_validate(monitor)


@router.post("/{device_id}/pause", response_model=MonitorResponse)
def pause_monitor(device_id: str, db: Session = Depends(get_db)):
    service = MonitorService(db)
    try:
        monitor = service.pause(device_id)
    except MonitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return MonitorResponse.model_validate(monitor)


@router.get("/{device_id}/history", response_model=list[MonitorEventResponse])
def get_monitor_history(device_id: str, db: Session = Depends(get_db)):
    service = MonitorService(db)
    try:
        events = service.history(device_id)
    except MonitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return [MonitorEventResponse.model_validate(e) for e in events]


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monitor(device_id: str, db: Session = Depends(get_db)):
    service = MonitorService(db)
    try:
        service.delete(device_id)
    except MonitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

@router.get("/events/all", response_model=list[GlobalMonitorEventResponse])
def get_all_events(
    event_type: EventType | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Global audit log across every monitor. Optional filters:
    - event_type: only events of one type (e.g. ALERT_TRIGGERED)
    - limit/offset: pagination (default 100 most recent events)
    """
    service = MonitorService(db)
    results = service.list_all_events(
        event_type=event_type, limit=limit, offset=offset
    )
    return [
        GlobalMonitorEventResponse(
            id=event.id,
            device_id=dev_id,
            event_type=event.event_type,
            message=event.message,
            created_at=event.created_at,
        )
        for event, dev_id in results
    ]


@router.post("/{device_id}/restore", response_model=MonitorResponse)
def restore_monitor(device_id: str, db: Session = Depends(get_db)):
    """Reverses a soft delete, bringing the monitor back into normal use.
    404 if the device doesn't exist, was never deleted, or has already
    been permanently purged past its retention period."""
    service = MonitorService(db)
    try:
        monitor = service.restore(device_id)
    except MonitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return MonitorResponse.model_validate(monitor)
