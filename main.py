import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.monitors import router as monitors_router
from app.scheduler.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(
    title="Pulse Check API",
    description="A Dead Man's Switch monitoring backend for remote devices.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(monitors_router)


@app.get("/", tags=["health"])
def root():
    return {"service": "Pulse Check API", "status": "ok"}
