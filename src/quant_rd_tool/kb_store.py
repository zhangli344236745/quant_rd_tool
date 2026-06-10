"""SQLite storage for finance knowledge base documents, chunks, and chat sessions."""

from __future__ import annotations

import json
import sqlite3
import struct
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from quant_rd_tool.config import settings


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def kb_root(data_dir: str | Path | None = None) -> Path:
    root = Path(data_dir or settings.kb_data_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "uploads").mkdir(parents=True, exist_ok=True)
    return root


def db_path(data_dir: str | Path | None = None) -> Path:
    return kb_root(data_dir) / "meta.db"


def sync_state_path(data_dir: str | Path | None = None) -> Path:
    return kb_root(data_dir) / "sync_state.json"


def pack_embedding(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_embedding(blob: bytes | None) -> list[float]:
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


@contextmanager
def connect(data_dir: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path(data_dir)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(data_dir: str | Path | None = None) -> None:
    with connect(data_dir) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                path TEXT,
                mime TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                ord INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding BLOB,
                meta_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                agent_id TEXT,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                citations_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id);
            """
        )


@dataclass
class DocumentRow:
    id: str
    title: str
    source: str
    path: str | None
    mime: str | None
    tags: list[str]
    updated_at: str
    chunk_count: int
    content_hash: str | None


def _row_to_doc(row: sqlite3.Row) -> DocumentRow:
    tags_raw = row["tags_json"] or "[]"
    try:
        tags = json.loads(tags_raw)
    except json.JSONDecodeError:
        tags = []
    if not isinstance(tags, list):
        tags = []
    return DocumentRow(
        id=row["id"],
        title=row["title"],
        source=row["source"],
        path=row["path"],
        mime=row["mime"],
        tags=[str(t) for t in tags],
        updated_at=row["updated_at"],
        chunk_count=int(row["chunk_count"] or 0),
        content_hash=row["content_hash"],
    )


def upsert_document(
    *,
    title: str,
    source: str,
    path: str | None = None,
    mime: str | None = None,
    tags: list[str] | None = None,
    content_hash: str | None = None,
    doc_id: str | None = None,
    data_dir: str | Path | None = None,
) -> str:
    init_db(data_dir)
    did = doc_id or str(uuid.uuid4())
    now = _now_iso()
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    with connect(data_dir) as conn:
        conn.execute(
            """
            INSERT INTO documents (id, title, source, path, mime, tags_json, updated_at, chunk_count, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                source=excluded.source,
                path=excluded.path,
                mime=excluded.mime,
                tags_json=excluded.tags_json,
                updated_at=excluded.updated_at,
                content_hash=excluded.content_hash
            """,
            (did, title, source, path, mime, tags_json, now, content_hash),
        )
    return did


def replace_chunks(
    doc_id: str,
    chunks: list[dict[str, Any]],
    *,
    data_dir: str | Path | None = None,
) -> int:
    init_db(data_dir)
    with connect(data_dir) as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        for i, ch in enumerate(chunks):
            cid = ch.get("id") or str(uuid.uuid4())
            emb = ch.get("embedding")
            blob = pack_embedding(emb) if emb else None
            meta = json.dumps(ch.get("meta") or {}, ensure_ascii=False)
            conn.execute(
                """
                INSERT INTO chunks (id, doc_id, ord, text, embedding, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cid, doc_id, i, ch["text"], blob, meta),
            )
        conn.execute(
            "UPDATE documents SET chunk_count = ?, updated_at = ? WHERE id = ?",
            (len(chunks), _now_iso(), doc_id),
        )
    return len(chunks)


def list_documents(
    *,
    tag: str | None = None,
    page: int = 1,
    page_size: int = 50,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    init_db(data_dir)
    page = max(1, page)
    offset = (page - 1) * page_size
    with connect(data_dir) as conn:
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY updated_at DESC"
        ).fetchall()
    docs = [_row_to_doc(r) for r in rows]
    if tag:
        docs = [d for d in docs if tag in d.tags]
    total = len(docs)
    items = docs[offset : offset + page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [d.__dict__ for d in items],
    }


def get_document(doc_id: str, *, data_dir: str | Path | None = None) -> DocumentRow | None:
    init_db(data_dir)
    with connect(data_dir) as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return _row_to_doc(row) if row else None


def delete_document(doc_id: str, *, data_dir: str | Path | None = None) -> bool:
    init_db(data_dir)
    with connect(data_dir) as conn:
        cur = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return cur.rowcount > 0


def iter_all_chunks(*, data_dir: str | Path | None = None) -> list[dict[str, Any]]:
    init_db(data_dir)
    with connect(data_dir) as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.doc_id, c.ord, c.text, c.embedding, c.meta_json,
                   d.title, d.path, d.tags_json
            FROM chunks c
            JOIN documents d ON d.id = c.doc_id
            ORDER BY c.doc_id, c.ord
            """
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            tags = json.loads(row["tags_json"] or "[]")
        except json.JSONDecodeError:
            tags = []
        out.append(
            {
                "id": row["id"],
                "doc_id": row["doc_id"],
                "ord": row["ord"],
                "text": row["text"],
                "embedding": unpack_embedding(row["embedding"]),
                "meta": json.loads(row["meta_json"] or "{}"),
                "doc_title": row["title"],
                "doc_path": row["path"],
                "tags": tags if isinstance(tags, list) else [],
            }
        )
    return out


def get_stats(*, data_dir: str | Path | None = None) -> dict[str, Any]:
    init_db(data_dir)
    with connect(data_dir) as conn:
        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        session_count = conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0]
    sync_path = sync_state_path(data_dir)
    last_sync: str | None = None
    if sync_path.exists():
        try:
            data = json.loads(sync_path.read_text(encoding="utf-8"))
            last_sync = data.get("last_sync_at")
        except Exception:
            pass
    return {
        "doc_count": doc_count,
        "chunk_count": chunk_count,
        "session_count": session_count,
        "last_sync_at": last_sync,
    }


def create_session(
    title: str | None = None,
    *,
    data_dir: str | Path | None = None,
) -> str:
    init_db(data_dir)
    sid = str(uuid.uuid4())
    now = _now_iso()
    with connect(data_dir) as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions (id, agent_id, title, created_at, updated_at)
            VALUES (?, NULL, ?, ?, ?)
            """,
            (sid, title or "新对话", now, now),
        )
    return sid


def get_session(session_id: str, *, data_dir: str | Path | None = None) -> dict[str, Any] | None:
    init_db(data_dir)
    with connect(data_dir) as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if not row:
        return None
    return dict(row)


def update_session_agent(
    session_id: str,
    agent_id: str,
    *,
    title: str | None = None,
    data_dir: str | Path | None = None,
) -> None:
    init_db(data_dir)
    now = _now_iso()
    with connect(data_dir) as conn:
        if title:
            conn.execute(
                "UPDATE chat_sessions SET agent_id = ?, title = ?, updated_at = ? WHERE id = ?",
                (agent_id, title, now, session_id),
            )
        else:
            conn.execute(
                "UPDATE chat_sessions SET agent_id = ?, updated_at = ? WHERE id = ?",
                (agent_id, now, session_id),
            )


def add_message(
    session_id: str,
    role: str,
    content: str,
    *,
    citations: list[dict[str, Any]] | None = None,
    data_dir: str | Path | None = None,
) -> str:
    init_db(data_dir)
    mid = str(uuid.uuid4())
    now = _now_iso()
    cites = json.dumps(citations or [], ensure_ascii=False)
    with connect(data_dir) as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (id, session_id, role, content, citations_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (mid, session_id, role, content, cites, now),
        )
        conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
    return mid


def list_sessions(
    *,
    limit: int = 30,
    data_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    init_db(data_dir)
    with connect(data_dir) as conn:
        rows = conn.execute(
            "SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_messages(
    session_id: str,
    *,
    data_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    init_db(data_dir)
    with connect(data_dir) as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, citations_json, created_at
            FROM chat_messages WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            cites = json.loads(row["citations_json"] or "[]")
        except json.JSONDecodeError:
            cites = []
        out.append(
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "role": row["role"],
                "content": row["content"],
                "citations": cites,
                "created_at": row["created_at"],
            }
        )
    return out
