import asyncio

import pytest

from models import MonitorDownError, MonitorRegistry


@pytest.mark.asyncio
async def test_register_starts_active():
    reg = MonitorRegistry()
    monitor = await reg.register("dev-1", timeout=5, alert_email="a@b.com")
    assert monitor.status == "active"


@pytest.mark.asyncio
async def test_heartbeat_just_before_expiry_wins_the_race():
    """The critical case: a heartbeat with very little time left must still
    reset the timer, not lose to the expiry that's about to fire."""
    reg = MonitorRegistry()
    await reg.register("dev-1", timeout=1, alert_email="a@b.com")

    await asyncio.sleep(0.85)
    await reg.heartbeat("dev-1")

    await asyncio.sleep(0.3)  # would be past the ORIGINAL 1s deadline
    assert reg.get("dev-1").status == "active"


@pytest.mark.asyncio
async def test_silent_monitor_goes_down():
    reg = MonitorRegistry()
    await reg.register("dev-1", timeout=1, alert_email="a@b.com")
    await asyncio.sleep(1.2)
    assert reg.get("dev-1").status == "down"


@pytest.mark.asyncio
async def test_heartbeat_on_down_monitor_is_rejected():
    reg = MonitorRegistry()
    await reg.register("dev-1", timeout=1, alert_email="a@b.com")
    await asyncio.sleep(1.2)
    with pytest.raises(MonitorDownError):
        await reg.heartbeat("dev-1")


@pytest.mark.asyncio
async def test_pause_stops_the_countdown_entirely():
    reg = MonitorRegistry()
    await reg.register("dev-1", timeout=1, alert_email="a@b.com")
    await reg.pause("dev-1")
    await asyncio.sleep(1.3)  # well past the original timeout
    assert reg.get("dev-1").status == "paused"


@pytest.mark.asyncio
async def test_heartbeat_unpauses_and_restarts_timer():
    reg = MonitorRegistry()
    await reg.register("dev-1", timeout=1, alert_email="a@b.com")
    await reg.pause("dev-1")
    await reg.heartbeat("dev-1")
    assert reg.get("dev-1").status == "active"