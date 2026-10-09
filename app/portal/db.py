"""SQLite storage for the mock portal. Synthetic data only."""

from __future__ import annotations

import json
import sqlite3

from app.config import DATA_DIR

DB_PATH = DATA_DIR / "portal.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                receipt_id TEXT,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                submitted_at TEXT
            )
            """
        )
        # migrate the M1 table (payload + created_at only)
        cols = _columns(conn, "applications")
        for name, ddl in (
            ("status", "TEXT NOT NULL DEFAULT 'draft'"),
            ("receipt_id", "TEXT"),
            ("updated_at", "TEXT"),
            ("submitted_at", "TEXT"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE applications ADD COLUMN {name} {ddl}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submission_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER,
                token TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )


def _latest(conn: sqlite3.Connection, user_id: str, status: str | None = None) -> sqlite3.Row | None:
    if status:
        return conn.execute(
            "SELECT * FROM applications WHERE user_id = ? AND status = ? ORDER BY id DESC LIMIT 1",
            (user_id, status),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM applications WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
    ).fetchone()


def latest_draft(user_id: str) -> dict | None:
    with _connect() as conn:
        row = _latest(conn, user_id, "draft")
    return dict(row) if row else None


def latest_submitted(user_id: str) -> dict | None:
    with _connect() as conn:
        row = _latest(conn, user_id, "submitted")
    return dict(row) if row else None


def draft_payload(user_id: str) -> dict:
    draft = latest_draft(user_id)
    return json.loads(draft["payload"]) if draft else {}


def save_section(user_id: str, section: dict) -> int:
    """Merge a dict of fields into the draft (creates it if missing). Returns application id."""
    with _connect() as conn:
        row = _latest(conn, user_id, "draft")
        if row:
            payload = json.loads(row["payload"])
            payload.update(section)
            conn.execute(
                "UPDATE applications SET payload = ?, updated_at = datetime('now') WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False), row["id"]),
            )
            return row["id"]
        cursor = conn.execute(
            "INSERT INTO applications (user_id, payload) VALUES (?, ?)",
            (user_id, json.dumps(section, ensure_ascii=False)),
        )
        return cursor.lastrowid


def submit(user_id: str, *, duplicate_trap: bool = False, token: str | None = None) -> dict | None:
    """Submit the current application.

    Normal mode: if already submitted, return the existing application (no duplicate).
    Trap mode: every call creates a new submitted application (portal does not help).
    """
    with _connect() as conn:
        if not duplicate_trap:
            existing = _latest(conn, user_id, "submitted")
            if existing:
                conn.execute(
                    "INSERT INTO submission_attempts (application_id, token) VALUES (?, ?)",
                    (existing["id"], token),
                )
                return dict(existing)

        draft = _latest(conn, user_id, "draft")
        if draft is not None:
            app_id = draft["id"]
        else:
            last = _latest(conn, user_id)
            if last is None:
                return None
            cursor = conn.execute(
                """
                INSERT INTO applications (user_id, status, payload, submitted_at, updated_at)
                VALUES (?, 'submitted', ?, datetime('now'), datetime('now'))
                """,
                (user_id, last["payload"]),
            )
            app_id = cursor.lastrowid

        receipt_id = f"SCH-2026-{app_id:06d}"
        conn.execute(
            """
            UPDATE applications
            SET status = 'submitted', receipt_id = ?, submitted_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
            """,
            (receipt_id, app_id),
        )
        conn.execute(
            "INSERT INTO submission_attempts (application_id, token) VALUES (?, ?)",
            (app_id, token),
        )
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        return dict(row)


def get_by_receipt(user_id: str, receipt_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE user_id = ? AND receipt_id = ?",
            (user_id, receipt_id),
        ).fetchone()
    return dict(row) if row else None


def count_submitted(user_id: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM applications WHERE user_id = ? AND status = 'submitted'",
            (user_id,),
        ).fetchone()
    return row["n"]


def reset(user_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM applications WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM submission_attempts")
