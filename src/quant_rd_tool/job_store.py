"""SQLite-backed async job queue for long-running stock analysis tasks."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    code TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    message TEXT,
    result_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    progress REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, id);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["payload"] = json.loads(out.get("payload") or "{}")
    return out


class JobStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def create(
        self,
        *,
        type: str,
        code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = _now_iso()
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, type, code, payload, status, progress, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', 0, ?, ?)
                """,
                (job_id, type, code, payload_json, now, now),
            )
            conn.commit()
        got = self.get(job_id)
        assert got is not None
        return got

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def list_jobs(
        self,
        *,
        status: str | None = None,
        type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if type:
            clauses.append("type = ?")
            params.append(type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 200)))
        sql = f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def _update(self, job_id: str, **fields: Any) -> None:
        if "payload" in fields and isinstance(fields["payload"], dict):
            fields["payload"] = json.dumps(fields["payload"], ensure_ascii=False)
        fields["updated_at"] = _now_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [job_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", vals)
            conn.commit()

    def mark_running(self, job_id: str, *, message: str = "") -> None:
        self._update(job_id, status="running", message=message or None)

    def mark_progress(self, job_id: str, progress: float, *, message: str = "") -> None:
        p = max(0.0, min(1.0, float(progress)))
        self._update(job_id, progress=p, message=message or None)
        if message:
            self.append_event(job_id, "info", message, progress=p)

    def mark_done(
        self,
        job_id: str,
        *,
        result_path: str = "",
        message: str = "done",
    ) -> None:
        self._update(
            job_id,
            status="done",
            progress=1.0,
            result_path=result_path or None,
            message=message,
            error=None,
        )
        self.append_event(job_id, "info", message or "done", progress=1.0)

    def mark_failed(self, job_id: str, *, error: str) -> None:
        err = (error or "unknown error")[:2048]
        self._update(job_id, status="failed", message="failed", error=err)
        self.append_event(job_id, "error", err, progress=None)

    def append_event(
        self,
        job_id: str,
        level: str,
        message: str,
        *,
        progress: float | None = None,
    ) -> dict[str, Any]:
        now = _now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO job_events (job_id, level, message, progress, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, level[:32], (message or "")[:2048], progress, now),
            )
            conn.commit()
            event_id = int(cur.lastrowid or 0)
        return {
            "id": event_id,
            "job_id": job_id,
            "level": level,
            "message": message,
            "progress": progress,
            "created_at": now,
        }

    def list_events(
        self,
        job_id: str,
        *,
        after_id: int = 0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, job_id, level, message, progress, created_at
                FROM job_events
                WHERE job_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (job_id, after_id, max(1, min(limit, 500))),
            ).fetchall()
        return [dict(r) for r in rows]

    def schedule_retry(self, job_id: str, *, error: str = "") -> bool:
        job = self.get(job_id)
        if not job:
            return False
        payload = dict(job.get("payload") or {})
        attempt = int(payload.get("_attempt") or 1)
        max_attempts = int(payload.get("max_attempts") or 1)
        if attempt >= max_attempts:
            return False
        payload["_attempt"] = attempt + 1
        self._update(
            job_id,
            status="queued",
            error=None,
            message=f"retry {attempt + 1}/{max_attempts}",
            payload=payload,
        )
        self.append_event(
            job_id,
            "warn",
            f"retry {attempt + 1}/{max_attempts}: {(error or '')[:500]}",
        )
        return True

    def requeue_failed_job(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job["status"] != "failed":
            return False
        payload = dict(job.get("payload") or {})
        max_attempts = int(payload.get("max_attempts") or 1)
        attempt = int(payload.get("_attempt") or 1)
        if attempt >= max_attempts:
            payload["max_attempts"] = max_attempts + 1
        return self.schedule_retry(job_id, error=job.get("error") or "")

    def mark_cancelled(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job["status"] != "queued":
            return False
        self._update(job_id, status="cancelled", message="cancelled")
        return True

    def recover_stale_running(self, *, reason: str = "interrupted: server restarted") -> int:
        """Mark orphaned ``running`` jobs after process restart."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET status = 'failed', error = ?, message = 'interrupted', updated_at = ?
                WHERE status = 'running'
                """,
                (reason[:2048], _now_iso()),
            )
            conn.commit()
            return int(cur.rowcount or 0)

    def claim_next_queued(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            job_id = row["id"]
            now = _now_iso()
            cur = conn.execute(
                """
                UPDATE jobs SET status = 'running', updated_at = ?, message = 'starting'
                WHERE id = ? AND status = 'queued'
                """,
                (now, job_id),
            )
            conn.commit()
            if cur.rowcount != 1:
                return None
        return self.get(job_id)
