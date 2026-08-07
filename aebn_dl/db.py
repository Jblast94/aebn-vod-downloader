from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

_DB_PATH = os.getenv("AEBNDL_DB_PATH", "")
_db_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_db_path() -> str:
    if _DB_PATH:
        return _DB_PATH
    output_dir = os.getenv("AEBNDL_OUTPUT_DIR", "")
    if output_dir:
        return str(Path(output_dir) / "aebndl-jobs.db")
    return str(Path.home() / ".aebndl-jobs.db")


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = _get_db_path()
        os.makedirs(Path(path).parent, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                output_paths TEXT NOT NULL DEFAULT '[]',
                subtitle_status TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                options TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.commit()
        _conn = conn
    return _conn


def save_job(job_dict: dict) -> None:
    conn = _connect()
    with _db_lock:
        conn.execute(
            """
            INSERT INTO jobs (id, url, status, created_at, updated_at, output_paths, subtitle_status, error, options)
            VALUES (:id, :url, :status, :created_at, :updated_at, :output_paths, :subtitle_status, :error, :options)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                updated_at=excluded.updated_at,
                output_paths=excluded.output_paths,
                subtitle_status=excluded.subtitle_status,
                error=excluded.error
            """,
            {
                "id": job_dict["id"],
                "url": job_dict["url"],
                "status": job_dict["status"],
                "created_at": job_dict["created_at"],
                "updated_at": job_dict["updated_at"],
                "output_paths": json.dumps(job_dict.get("output_paths", [])),
                "subtitle_status": json.dumps(job_dict.get("subtitle_status_raw", {})),
                "error": job_dict.get("error", ""),
                "options": json.dumps(job_dict.get("options", {})),
            },
        )
        conn.commit()


def delete_job_record(job_id: str) -> None:
    conn = _connect()
    with _db_lock:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()


def load_all_jobs() -> list[dict]:
    conn = _connect()
    with _db_lock:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at ASC").fetchall()
    result = []
    for row in rows:
        result.append({
            "id": row["id"],
            "url": row["url"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "output_paths": json.loads(row["output_paths"]),
            "subtitle_status_raw": json.loads(row["subtitle_status"]),
            "error": row["error"],
            "options": json.loads(row["options"]),
        })
    return result


def is_available() -> bool:
    try:
        _connect()
        return True
    except Exception:
        return False
