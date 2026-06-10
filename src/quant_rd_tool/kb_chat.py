"""Chat orchestration: retrieve → agent → citations."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from quant_rd_tool import kb_cursor_agent, kb_search, kb_store
from quant_rd_tool.config import settings

logger = logging.getLogger(__name__)

DISCLAIMER = kb_cursor_agent.DISCLAIMER


def _cursor_ready() -> bool:
    return kb_cursor_agent._cursor_available()


def chat(
    message: str,
    *,
    session_id: str | None = None,
    top_k: int = 8,
    tags: list[str] | None = None,
    data_dir: str | None = None,
    agent_factory: Any = None,
) -> dict[str, Any]:
    message = message.strip()
    if not message:
        raise ValueError("message is required")

    kb_store.init_db(data_dir)
    sid = session_id or kb_store.create_session(data_dir=data_dir)
    session = kb_store.get_session(sid, data_dir=data_dir)
    if not session:
        sid = kb_store.create_session(data_dir=data_dir)
        session = kb_store.get_session(sid, data_dir=data_dir)

    kb_store.add_message(sid, "user", message, data_dir=data_dir)

    hits = kb_search.retrieve(message, top_k=top_k, tags=tags, data_dir=data_dir)
    citations = kb_search.hits_to_citations(hits)

    agent_id = session.get("agent_id") if session else None
    answer, new_agent_id, backend, backend_error = kb_cursor_agent.resolve_answer_with_fallback(
        message,
        hits=hits,
        agent_id=agent_id,
        data_dir=data_dir,
        agent_factory=agent_factory,
    )
    if new_agent_id:
        kb_store.update_session_agent(sid, new_agent_id, data_dir=data_dir)

    kb_store.add_message(sid, "assistant", answer, citations=citations, data_dir=data_dir)
    out: dict[str, Any] = {
        "session_id": sid,
        "answer": answer,
        "citations": citations,
        "disclaimer": DISCLAIMER,
        "backend": backend,
    }
    if backend_error:
        out["backend_error"] = backend_error
    return out


def chat_stream(
    message: str,
    *,
    session_id: str | None = None,
    top_k: int = 8,
    tags: list[str] | None = None,
    data_dir: str | None = None,
    agent_factory: Any = None,
) -> Iterator[str]:
    """Yield SSE-formatted events: meta, token deltas, done."""
    message = message.strip()
    if not message:
        raise ValueError("message is required")

    kb_store.init_db(data_dir)
    sid = session_id or kb_store.create_session(data_dir=data_dir)
    session = kb_store.get_session(sid, data_dir=data_dir)
    agent_id = session.get("agent_id") if session else None

    kb_store.add_message(sid, "user", message, data_dir=data_dir)
    hits = kb_search.retrieve(message, top_k=top_k, tags=tags, data_dir=data_dir)
    citations = kb_search.hits_to_citations(hits)

    backend = "rag"
    parts: list[str] = []
    new_agent_id: str | None = None

    yield (
        "event: meta\n"
        f"data: {json.dumps({'session_id': sid, 'citations': citations, 'disclaimer': DISCLAIMER, 'backend': 'pending'}, ensure_ascii=False)}\n\n"
    )

    if _cursor_ready():
        try:
            kb_cursor_agent.stream_agent_meta = None
            for chunk in kb_cursor_agent.stream_agent_chat(
                message,
                agent_id=agent_id,
                context_chunks=hits,
                data_dir=data_dir,
                agent_factory=agent_factory,
            ):
                parts.append(chunk)
                yield f"event: token\ndata: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
            meta = kb_cursor_agent.stream_agent_meta
            if meta:
                backend = meta.backend
                new_agent_id = meta.agent_id
        except Exception as exc:
            logger.warning("Cursor stream failed: %s", exc)

    if not parts:
        answer, new_agent_id, backend, _backend_error = kb_cursor_agent.resolve_answer_with_fallback(
            message,
            hits=hits,
            agent_id=agent_id,
            data_dir=data_dir,
            agent_factory=agent_factory,
        )
        parts = [answer]
        yield f"event: token\ndata: {json.dumps({'text': answer}, ensure_ascii=False)}\n\n"

    if new_agent_id:
        kb_store.update_session_agent(sid, new_agent_id, data_dir=data_dir)

    answer = "".join(parts).strip() or "(无回复)"
    kb_store.add_message(sid, "assistant", answer, citations=citations, data_dir=data_dir)
    yield (
        "event: backend\n"
        f"data: {json.dumps({'backend': backend, 'session_id': sid}, ensure_ascii=False)}\n\n"
    )
    yield f"event: done\ndata: {json.dumps({'session_id': sid, 'backend': backend}, ensure_ascii=False)}\n\n"
