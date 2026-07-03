"""
Core monitor state machine.

    active  --pause-->     paused
    paused  --heartbeat--> active   (implicit un-pause)
    active  --heartbeat--> active   (timer reset)
    active  --timeout-->   down
"""

import asyncio
import json
import time
from dataclasses import dataclass, field


class MonitorNotFoundError(Exception):
    pass


class MonitorAlreadyExistsError(Exception):
    pass


class MonitorDownError(Exception):
    """A heartbeat arrived for a monitor that already fired its alert."""


@dataclass
class Monitor:
    id: str
    timeout: int
    alert_email: str
    status: str = "active"
    created_at: float = field(default_factory=time.time)
    _task: asyncio.Task | None = field(default=None, repr=False, compare=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "timeout": self.timeout,
            "alert_email": self.alert_email,
            "created_at": self.created_at,
        }


class MonitorRegistry:
    def __init__(self) -> None:
        self._monitors: dict[str, Monitor] = {}

    def get(self, monitor_id: str) -> Monitor:
        monitor = self._monitors.get(monitor_id)
        if monitor is None:
            raise MonitorNotFoundError(monitor_id)
        return monitor

    async def register(self, monitor_id: str, timeout: int, alert_email: str) -> Monitor:
        if monitor_id in self._monitors:
            raise MonitorAlreadyExistsError(monitor_id)
        monitor = Monitor(id=monitor_id, timeout=timeout, alert_email=alert_email)
        self._monitors[monitor_id] = monitor

        # Timer starts the instant registration succeeds -- a device that
        # never sends a single heartbeat must still be caught as down.
        monitor._task = asyncio.create_task(self._run_countdown(monitor))
        return monitor

    async def heartbeat(self, monitor_id: str) -> Monitor:
        monitor = self.get(monitor_id)

        async with monitor._lock:
            if monitor.status == "down":
                # A monitor that already alerted needs a human to look at it,
                # not a silent auto-revival from a late-arriving ping.
                raise MonitorDownError(monitor_id)

            if monitor._task and not monitor._task.done():
                monitor._task.cancel()
            monitor.status = "active"
            monitor._task = asyncio.create_task(self._run_countdown(monitor))

        return monitor

    async def pause(self, monitor_id: str) -> Monitor:
        monitor = self.get(monitor_id)

        async with monitor._lock:
            if monitor.status == "down":
                raise MonitorDownError(monitor_id)
            if monitor._task and not monitor._task.done():
                monitor._task.cancel()
            monitor.status = "paused"
            monitor._task = None

        return monitor

    async def _run_countdown(self, monitor: Monitor) -> None:
        try:
            await asyncio.sleep(monitor.timeout)
        except asyncio.CancelledError:
            # A heartbeat cancelled us before expiry -- this is success,
            # not an error. Just exit quietly.
            return

        async with monitor._lock:
            # Re-check status INSIDE the lock, right before firing. Without
            # this, a heartbeat landing in the gap between "sleep finished"
            # and "lock acquired" could get silently overwritten.
            if monitor.status == "active":
                monitor.status = "down"
                fire_alert(monitor)


def fire_alert(monitor: Monitor) -> None:
    print(json.dumps({"ALERT": f"Device {monitor.id} is down!", "time": time.time()}))