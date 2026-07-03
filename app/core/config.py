from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Pulse Check API"
    database_url: str
    debug: bool = False

    class Config:
        env_file = ".env"


settings = Settings()
