import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            # WAL is stored in the database file, so it only needs to be set once.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    filters_json TEXT NOT NULL,
                    checkpoint_json TEXT NOT NULL DEFAULT '{}',
                    found INTEGER NOT NULL DEFAULT 0,
                    downloaded INTEGER NOT NULL DEFAULT 0,
                    uploaded INTEGER NOT NULL DEFAULT 0,
                    duplicates INTEGER NOT NULL DEFAULT 0,
                    errors INTEGER NOT NULL DEFAULT 0,
                    current_item TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    process TEXT,
                    process_class TEXT,
                    content_type TEXT NOT NULL,
                    document_date TEXT,
                    source_url TEXT NOT NULL,
                    pdf_url TEXT,
                    local_path TEXT,
                    drive_file_id TEXT,
                    status TEXT NOT NULL,
                    hash_sha256 TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS documents_status_idx ON documents(status);
                CREATE INDEX IF NOT EXISTS documents_hash_idx ON documents(hash_sha256);
                CREATE INDEX IF NOT EXISTS documents_date_idx ON documents(document_date);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job_documents (
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'discovered',
                    PRIMARY KEY (job_id, document_id)
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def get_setting(self, key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str | None) -> None:
        """Save a setting; None removes it, so the default applies again."""
        with self.connect() as connection:
            if value is None:
                connection.execute("DELETE FROM app_settings WHERE key = ?", (key,))
            else:
                connection.execute(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )

    def create_job(self, job_id: str, filters: dict[str, Any]) -> None:
        timestamp = _now()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO jobs (id, status, filters_json, created_at, updated_at) "
                "VALUES (?, 'queued', ?, ?, ?)",
                (job_id, json.dumps(filters, ensure_ascii=False), timestamp, timestamp),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def update_job(self, job_id: str, **values: Any) -> None:
        allowed = {
            "status",
            "checkpoint_json",
            "found",
            "downloaded",
            "uploaded",
            "duplicates",
            "errors",
            "current_item",
            "error",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                (*updates.values(), job_id),
            )

    def add_event(self, job_id: str, level: str, message: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO events (job_id, level, message, created_at) VALUES (?, ?, ?, ?)",
                (job_id, level, message[:2000], _now()),
            )

    def list_events(self, job_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, level, message, created_at FROM events "
                "WHERE job_id = ? ORDER BY id DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def insert_document(self, document: dict[str, Any]) -> dict[str, Any]:
        timestamp = _now()
        columns = (
            "document_key",
            "title",
            "process",
            "process_class",
            "content_type",
            "document_date",
            "source_url",
            "pdf_url",
            "status",
            "created_at",
            "updated_at",
        )
        values = [document.get(column) for column in columns[:-2]]
        values.extend((timestamp, timestamp))
        with self.connect() as connection:
            cursor = connection.execute(
                f"INSERT OR IGNORE INTO documents ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                values,
            )
            row = connection.execute(
                "SELECT * FROM documents WHERE document_key = ?",
                (document["document_key"],),
            ).fetchone()
        return dict(row)

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return dict(row) if row else None

    def link_job_document(self, job_id: str, document_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO job_documents (job_id, document_id) VALUES (?, ?)",
                (job_id, document_id),
            )
        return cursor.rowcount == 1

    def update_job_document_status(self, job_id: str, document_id: int, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE job_documents SET status = ? WHERE job_id = ? AND document_id = ?",
                (status, job_id, document_id),
            )

    def job_counts(self, job_id: str) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS found,
                    SUM(CASE WHEN status IN ('downloaded', 'uploaded', 'error_upload')
                        THEN 1 ELSE 0 END) AS downloaded,
                    SUM(CASE WHEN status = 'uploaded' THEN 1 ELSE 0 END) AS uploaded,
                    SUM(CASE WHEN status = 'duplicate' THEN 1 ELSE 0 END) AS duplicates,
                    SUM(CASE WHEN status IN ('error_download', 'error_upload')
                        THEN 1 ELSE 0 END) AS errors
                FROM job_documents WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}

    def find_document_by_hash(self, digest: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                # A "duplicate" row has no file of its own, so it can never be the original.
                "SELECT * FROM documents WHERE hash_sha256 = ? AND status != 'duplicate' "
                "ORDER BY id LIMIT 1",
                (digest,),
            ).fetchone()
        return dict(row) if row else None

    def update_document(self, document_id: int, **values: Any) -> None:
        allowed = {
            "local_path",
            "drive_file_id",
            "status",
            "hash_sha256",
            "attempts",
            "error",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE documents SET {assignments} WHERE id = ?",
                (*updates.values(), document_id),
            )

    def list_documents(
        self,
        *,
        content_type: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if content_type:
            clauses.append("content_type = ?")
            parameters.append(content_type)
        if status:
            clauses.append("status = ?")
            parameters.append(status)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM documents {where_clause} "
                "ORDER BY document_date DESC, id DESC LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def interrupt_running_jobs(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id FROM jobs WHERE status IN ('running', 'queued')").fetchall()
            job_ids = [row["id"] for row in rows]
            connection.execute(
                "UPDATE jobs SET status = 'interrupted', "
                "error = 'Processo encerrado antes da conclusão', updated_at = ? "
                "WHERE status IN ('running', 'queued')",
                (_now(),),
            )
        return job_ids