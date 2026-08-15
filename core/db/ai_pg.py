"""Postgres persistence for AI smart-reply state (production)."""

from __future__ import annotations

import json

from core.db.connection import get_connection

_TABLE = "ai_smart_reply_store"


def ensure_table() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    id TEXT PRIMARY KEY,
                    payload JSONB NOT NULL DEFAULT '{{}}'::jsonb
                )
                """
            )


def pg_load() -> dict:
    ensure_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT payload FROM {_TABLE} WHERE id = %s LIMIT 1",
                ("default",),
            )
            row = cur.fetchone()
    if not row:
        return {}
    payload = row[0]
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {}
    return {}


def pg_save(data: dict) -> None:
    ensure_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_TABLE} (id, payload)
                VALUES (%s, %s::jsonb)
                ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                ("default", json.dumps(data, ensure_ascii=False)),
            )
