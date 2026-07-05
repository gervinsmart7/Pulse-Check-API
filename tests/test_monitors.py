import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.scheduler import scheduler as scheduler_module
import main as main_module
from main import app

# Isolated in-memory SQLite DB shared across a single test's connections.
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
scheduler_module._session_factory = TestingSessionLocal


@pytest.fixture(autouse=True)
def _fresh_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def register(client, device_id="device-123", timeout=60, email="admin@critmon.com"):
    return client.post(
        "/monitors", json={"id": device_id, "timeout": timeout, "alert_email": email}
    )


def test_register_monitor_returns_201(client):
    resp = register(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["monitor"]["id"] == "device-123"
    assert body["monitor"]["status"] == "ACTIVE"


def test_register_duplicate_device_returns_409(client):
    register(client)
    resp = register(client)
    assert resp.status_code == 409


def test_heartbeat_resets_timer_and_returns_200(client):
    register(client)
    resp = client.post("/monitors/device-123/heartbeat")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACTIVE"


def test_heartbeat_unknown_device_returns_404(client):
    resp = client.post("/monitors/does-not-exist/heartbeat")
    assert resp.status_code == 404


def test_pause_then_heartbeat_resumes_monitoring(client):
    register(client)
    pause_resp = client.post("/monitors/device-123/pause")
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "PAUSED"

    hb_resp = client.post("/monitors/device-123/heartbeat")
    assert hb_resp.status_code == 200
    assert hb_resp.json()["status"] == "ACTIVE"


def test_monitor_goes_down_after_timeout_and_logs_event(client):
    register(client, timeout=1)
    time.sleep(2.5)

    resp = client.get("/monitors/device-123")
    assert resp.status_code == 200
    assert resp.json()["status"] == "DOWN"

    history = client.get("/monitors/device-123/history").json()
    event_types = [e["event_type"] for e in history]
    assert "ALERT_TRIGGERED" in event_types


def test_history_contains_full_audit_trail(client):
    register(client, timeout=60)
    client.post("/monitors/device-123/pause")
    client.post("/monitors/device-123/heartbeat")

    history = client.get("/monitors/device-123/history").json()
    event_types = [e["event_type"] for e in history]
    assert event_types == [
        "MONITOR_CREATED",
        "PAUSED",
        "RESUMED",
        "HEARTBEAT_RECEIVED",
    ]


def test_list_and_delete_monitor(client):
    register(client)
    assert len(client.get("/monitors").json()) == 1

    del_resp = client.delete("/monitors/device-123")
    assert del_resp.status_code == 204
    assert client.get("/monitors/device-123").status_code == 404


def test_restore_reverses_soft_delete(client):
    register(client, device_id="restore-test")
    client.delete("/monitors/restore-test")

    assert client.get("/monitors/restore-test").status_code == 404

    restore_resp = client.post("/monitors/restore-test/restore")
    assert restore_resp.status_code == 200
    assert restore_resp.json()["status"] == "ACTIVE"

    get_resp = client.get("/monitors/restore-test")
    assert get_resp.status_code == 200

    history = client.get("/monitors/restore-test/history").json()
    event_types = [e["event_type"] for e in history]
    assert event_types == ["MONITOR_CREATED", "DELETED", "RESTORED"]


def test_restore_non_deleted_monitor_returns_404(client):
    register(client, device_id="never-deleted")
    resp = client.post("/monitors/never-deleted/restore")
    assert resp.status_code == 404
