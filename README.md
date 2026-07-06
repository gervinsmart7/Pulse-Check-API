# Pulse Check API

A Dead Man's Switch API for CritMon Servers Inc. Devices register a monitor
with a timeout. If the device fails to send a heartbeat before the timer
expires, the system marks it down and fires an alert. Built with FastAPI
and Postgres.

---

## Architecture

### Sequence Diagram

![Sequence Diagram](docs/sequence_diagram.png)

### State Flowchart

![State Flowchart](docs/flowchart.png)

### How It Works

Each monitor is a row in Postgres with a `timeout` and a `last_heartbeat`
timestamp — there's no in-memory countdown or per-monitor timer object. A
background scheduler (APScheduler) ticks once a second, loads every `ACTIVE`
monitor, and computes elapsed time as `now - last_heartbeat`. Any monitor
where that elapsed time exceeds its `timeout` is transitioned to `DOWN` and
an alert is logged, in the same pass.

Because state lives in the database rather than in memory, there's nothing
to rebuild on restart — the next scheduler tick after startup immediately
re-evaluates every monitor against its real `last_heartbeat`, so a restart
can never "lose" a countdown or delay detection of a monitor that expired
while the process was down.

Paused and deleted monitors are excluded from the scheduler's query
entirely, so they incur zero timeout-checking overhead. A heartbeat on a
paused monitor resumes it to `ACTIVE`. A heartbeat on a `DOWN` monitor also
returns it directly to `ACTIVE` — recovery is immediate, not staged (see
Developer's Choice below for why a **reversible delete**, not a graduated
recovery state, was the extension chosen for this project).

### Live URL

https://pulse-check-api-xcng.onrender.com

Interactive API docs (test every endpoint from the browser):
https://pulse-check-api-xcng.onrender.com/docs

> Runs on Render's free tier, which sleeps after 15 minutes of inactivity.
> The first request after idling may take up to a minute to wake it back up.

---

## Stack

- **Language:** Python 3.12
- **Framework:** FastAPI
- **Server:** Uvicorn
- **Database:** PostgreSQL via SQLAlchemy
- **Migrations:** Alembic
- **Scheduler:** APScheduler
- **Validation:** Pydantic
- **Deployment:** Docker on Render

---

## Setup

### Prerequisites

- Python 3.11+
- Docker + Docker Compose
- `libpq-dev`, `python3-dev`, `build-essential` (for building `psycopg2-binary`)

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv python3-dev \
    build-essential libpq-dev git curl unzip
```

### Local Development

```bash
git clone https://github.com/gervinsmart7/Pulse-Check-API
cd Pulse-Check-API
docker compose up -d          # starts Postgres
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn main:app --reload --port 8000
```

### Docker (app + migrations in one container)

```bash
docker build -t pulse-check-api .
docker run --rm --network host \
  -e DATABASE_URL="postgresql+psycopg2://pulsecheck:pulsecheck@localhost:5433/pulsecheck" \
  -e PORT=8080 \
  pulse-check-api
```

Migrations run automatically on container startup via `entrypoint.sh`
before Uvicorn starts.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | - | Postgres connection string |
| `SCHEDULER_INTERVAL_SECONDS` | No | `1` | How often the timeout-check job runs |
| `PORT` | No | `8080` (Docker) / `8000` (local) | Port the server listens on |

---

## API

### Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/monitors` | Register a monitor |
| `POST` | `/monitors/{id}/heartbeat` | Send a heartbeat |
| `POST` | `/monitors/{id}/pause` | Pause a monitor |
| `POST` | `/monitors/{id}/restore` | Reverse a soft delete |
| `GET` | `/monitors/{id}` | Get monitor state |
| `GET` | `/monitors` | List all active monitors |
| `GET` | `/monitors/{id}/history` | Full audit trail for one device |
| `GET` | `/monitors/events/all` | Global audit log across all monitors |
| `DELETE` | `/monitors/{id}` | Soft-delete a monitor |

### Register a Monitor

```
POST /monitors
```

```json
{
  "id": "device-123",
  "timeout": 60,
  "alert_email": "admin@critmon.com"
}
```

| Field | Type | Required | Constraints |
|---|---|---|---|
| `id` | string | Yes | 1-255 chars |
| `timeout` | int | Yes | > 0 seconds |
| `alert_email` | string | Yes | Valid email format |

Response `201 Created`:

```json
{
  "message": "Monitor 'device-123' registered successfully",
  "monitor": {
    "id": "device-123",
    "timeout": 60,
    "alert_email": "admin@critmon.com",
    "status": "ACTIVE",
    "last_heartbeat": "2026-07-05T12:00:00Z",
    "created_at": "2026-07-05T12:00:00Z",
    "updated_at": "2026-07-05T12:00:00Z"
  }
}
```

`409 Conflict` if `id` already exists.

### Heartbeat
POST /monitors/{id}/heartbeat
Response `200 OK`: the updated monitor object. Behavior depends on prior state:

| Prior state | Result |
|---|---|
| `ACTIVE` | Timer resets, stays `ACTIVE` |
| `PAUSED` | Auto-resumes to `ACTIVE` |
| `DOWN` | Recovers to `ACTIVE` |

`404 Not Found` if the device doesn't exist or has been deleted.

### Pause
POST /monitors/{id}/pause
Response `200 OK` with the updated monitor, now `PAUSED`. No timeout checks
occur while paused. Calling heartbeat on a paused monitor resumes it.

### Restore
POST /monitors/{id}/restore
Response `200 OK` with the monitor restored to normal use, exact same
registration data intact.

`404 Not Found` if the device never existed, was never deleted, or was
soft-deleted long enough ago to have already been permanently purged (see
retention policy below).

### Get Specific Monitors
GET /monitors/{id}
Response `200 OK`:

```json
{
  "id": "device-123",
  "timeout": 60,
  "alert_email": "admin@critmon.com",
  "status": "ACTIVE",
  "last_heartbeat": "2026-07-05T12:00:00Z",
  "created_at": "2026-07-05T12:00:00Z",
  "updated_at": "2026-07-05T12:00:00Z"
}
```

### List Monitors
GET /monitors
Response `200 OK`: an array of monitor objects (same shape as above),
excluding soft-deleted monitors.

### Single-Device History
GET /monitors/{id}/history
Returns every event ever recorded for one device, oldest first — including
events from before a soft delete, since history outlives deletion until the
retention period expires.

```json
[
  {"event_type": "MONITOR_CREATED", "message": "...", "created_at": "..."},
  {"event_type": "HEARTBEAT_RECEIVED", "message": "...", "created_at": "..."},
  {"event_type": "DELETED", "message": "...", "created_at": "..."},
  {"event_type": "RESTORED", "message": "...", "created_at": "..."}
]
```

### Global Event Log
GET /monitors/events/all
| Query param | Required | Default | Description |
|---|---|---|---|
| `event_type` | No | - | Filter to one event type, e.g. `ALERT_TRIGGERED` |
| `limit` | No | `100` | Max results |
| `offset` | No | `0` | Pagination offset |

Returns events across **every** monitor, newest first, each tagged with its
`device_id`:

```json
[
  {
    "id": "72d65171-...",
    "device_id": "device-123",
    "event_type": "ALERT_TRIGGERED",
    "message": "Device 'device-123' missed its 60s heartbeat window",
    "created_at": "2026-07-05T21:36:04Z"
  }
]
```

### Delete Monitor
DELETE /monitors/{id}
Response `204 No Content`. This is a **soft delete** — see Developer's
Choice below.

### Error Responses

```json
{
  "detail": "Monitor 'device-123' not found"
}
```

| Status | Meaning |
|---|---|
| `400` | Invalid request body |
| `404` | Monitor not found |
| `409` | Duplicate device on registration |
| `500` | Internal server error |

---

## Developer's Choice: Reversible, Auditable, Retention-Bound Deletion

The base spec treats deletion as final: a monitor is either registered or
gone. In practice, mistakes happen — an admin deletes the wrong device ID,
or a device is decommissioned and later needs its incident history pulled
for a compliance review months afterward. A hard, irreversible delete
destroys exactly the information needed in both situations, at exactly the
moment it can no longer be recovered.

This is the same problem systems like Gmail's Trash, Google Drive's "Recently
deleted," and most database-backed SaaS products solve with soft delete: an
item marked deleted is hidden from normal use immediately, but not actually
destroyed until a retention window passes. The same principle applies here.

The design adds three things on top of the base spec:

**Soft delete:** `DELETE /monitors/{id}` sets `is_deleted = true` and
`deleted_at = now()` rather than removing the row. The monitor disappears
from `GET /monitors` and can no longer receive heartbeats or pauses, but
its row and every one of its `monitor_events` remain physically in the
database.

**Restore:** `POST /monitors/{id}/restore` reverses this — clears
`is_deleted`/`deleted_at` and logs a `RESTORED` event — bringing the
monitor back to normal use with its original data and full history intact,
undoing an accidental deletion cleanly.

**Retention purge:** a background job runs every 24 hours and permanently
deletes any monitor that has been soft-deleted for more than 6 months,
cascading to its events. This bounds database growth without requiring a
human to remember to clean up old records, while still guaranteeing a
generous recovery/audit window before anything is actually destroyed.

State transitions this adds on top of the base spec:
active/down/paused + delete            -> soft-deleted (history preserved)
soft-deleted        + restore           -> prior active use resumes
soft-deleted        + 6 months elapse   -> permanently purged (irreversible)
This gives CritMon a system where deletion is a safety-netted action rather
than a one-way door, and where the audit trail a support engineer needs
during an incident review can't accidentally be destroyed by the same
action that decommissions a device.

---

## Running Tests

```bash
pytest -v
```

Runs against an isolated in-memory SQLite database — no Docker or Postgres
required. Covers the full lifecycle: registration, duplicate detection,
heartbeat (including `DOWN → ACTIVE` recovery), pause/resume, timeout-
triggered alerts, full audit history, soft delete, restore (including the
guardrail against restoring a non-deleted monitor), and listing.
