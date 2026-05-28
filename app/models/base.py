def import_all_models() -> None:
    """Import all models so SQLAlchemy can register table metadata."""

    from app.models import asset, scan  # noqa: F401
