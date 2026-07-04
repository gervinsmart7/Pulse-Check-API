from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application configuration, loaded from environment / .env."""

    database_url: str = (
        "postgresql+psycopg2://pulsecheck:pulsecheck@localhost:5433/pulsecheck"
    )
    scheduler_interval_seconds: int = 1

    # How long a soft-deleted monitor's row and event history are retained
    # before being permanently purged from the database.
    retention_period_days: int = 180  # ~6 months

    # How often the purge job runs. Daily is plenty -- this isn't
    # time-sensitive the way heartbeat checking is.
    purge_interval_hours: int = 24

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
