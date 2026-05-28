from pathlib import Path
import os


class Settings:
    """Simple application settings."""

    BASE_DIR = Path(__file__).resolve().parents[2]

    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")


settings = Settings()
