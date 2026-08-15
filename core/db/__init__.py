"""Optional Postgres helpers — JSON file storage is used when DATABASE_URL is unset."""

from core.db.connection import get_connection, use_postgres

__all__ = ["get_connection", "use_postgres"]
