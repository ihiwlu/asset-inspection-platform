from datetime import datetime
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    pass


def create_tables() -> None:
    """Create all database tables."""

    from app.models.asset import Asset  # noqa: F401
    from app.models.scan import ScanResult  # noqa: F401

    prepare_sqlite_database()
    Base.metadata.create_all(bind=engine)


def prepare_sqlite_database() -> None:
    """Backup old incompatible SQLite databases before creating tables."""

    db_path = get_sqlite_path()
    if db_path is None:
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        return

    if not needs_schema_reset(db_path):
        return

    engine.dispose()
    backup_path = build_backup_path(db_path)
    db_path.replace(backup_path)
    print(f"Old database schema detected. Backup created: {backup_path}")


def get_sqlite_path() -> Path | None:
    if not settings.database_url.startswith("sqlite:///"):
        return None

    path_text = settings.database_url.replace("sqlite:///", "", 1)
    if path_text.startswith("./"):
        return Path(path_text)
    return Path(path_text)


def needs_schema_reset(db_path: Path) -> bool:
    """Return True when the existing DB was created by an older model version."""

    with sqlite3.connect(db_path) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

        old_tables = {"users", "scan_tasks", "vulnerabilities"}
        if table_names.intersection(old_tables):
            return True

        if "assets" in table_names:
            asset_columns = get_column_names(conn, "assets")
            if asset_columns != {"id", "ip_address", "created_at"}:
                return True

        if "scan_results" in table_names:
            result_columns = get_column_names(conn, "scan_results")
            if result_columns != {
                "id",
                "asset_id",
                "ip_address",
                "port",
                "service_name",
                "status",
                "scanned_at",
            }:
                return True

    return False


def get_column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def build_backup_path(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return db_path.with_name(f"{db_path.stem}_{timestamp}_backup{db_path.suffix}")


def get_db():
    """FastAPI dependency for database sessions."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
