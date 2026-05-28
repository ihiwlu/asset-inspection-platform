from pathlib import Path

from app.core.config import settings
from app.db.database import create_tables


def init_db() -> None:
    """Create database tables from SQLAlchemy models."""

    if settings.database_url.startswith("sqlite:///./"):
        db_path = Path(settings.database_url.replace("sqlite:///./", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    create_tables()


if __name__ == "__main__":
    init_db()
