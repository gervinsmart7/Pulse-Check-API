from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, Field

from models import (
    MonitorAlreadyExistsError,
    MonitorDownError,
    MonitorNotFoundError,
    MonitorRegistry,
)

app = FastAPI(title="Pulse-Check-API", version="1.0.0")
registry = MonitorRegistry()


class MonitorCreate(BaseModel):
    id: str = Field(min_length=1)
    timeout: int = Field(gt=0)
    alert_email: EmailStr


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/monitors", status_code=201)
async def create_monitor(payload: MonitorCreate):
    try:
        monitor = await registry.register(payload.id, payload.timeout, payload.alert_email)
    except MonitorAlreadyExistsError:
        raise HTTPException(status_code=409, detail=f"Monitor {payload.id} already exists")
    return {**monitor.to_dict(), "message": "Monitor created"}


@app.get("/monitors/{monitor_id}")
def get_monitor(monitor_id: str):
    try:
        monitor = registry.get(monitor_id)
    except MonitorNotFoundError:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")
    return monitor.to_dict()


@app.post("/monitors/{monitor_id}/heartbeat")
async def heartbeat(monitor_id: str):
    try:
        monitor = await registry.heartbeat(monitor_id)
    except MonitorNotFoundError:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")
    except MonitorDownError:
        raise HTTPException(
            status_code=409,
            detail=f"Monitor {monitor_id} is already down; requires manual re-registration",
        )
    return {**monitor.to_dict(), "message": "Heartbeat received, timer reset"}


@app.post("/monitors/{monitor_id}/pause")
async def pause(monitor_id: str):
    try:
        monitor = await registry.pause(monitor_id)
    except MonitorNotFoundError:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")
    except MonitorDownError:
        raise HTTPException(status_code=409, detail=f"Monitor {monitor_id} is already down")
    return {**monitor.to_dict(), "message": "Monitor paused"}