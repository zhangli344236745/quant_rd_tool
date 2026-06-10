"""Finance knowledge base REST + SSE routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from quant_rd_tool import kb_chat, kb_ingest, kb_store
from quant_rd_tool.config import settings
from quant_rd_tool import kb_sdk_agent
from quant_rd_tool.kb_cloud_agent import check_cursor_api, cloud_agent_available

router = APIRouter()


class ChatRequest(BaseModel):
    message: str | None = Field(default=None, description="User question")
    content: str | None = Field(default=None, description="Alias for message (legacy clients)")
    session_id: str | None = None
    stream: bool = False
    top_k: int = Field(8, ge=1, le=20)
    tags: list[str] | None = None

    @field_validator("session_id", mode="before")
    @classmethod
    def _empty_session_is_none(cls, v: Any) -> str | None:
        if v is None or v == "":
            return None
        return str(v)

    @field_validator("message", mode="before")
    @classmethod
    def _normalize_message(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("message must be a string")
        text = v.strip()
        return text or None

    @field_validator("content", mode="before")
    @classmethod
    def _normalize_content(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("content must be a string")
        text = v.strip()
        return text or None

    def resolved_message(self) -> str:
        text = (self.message or self.content or "").strip()
        if not text:
            raise ValueError("message is required")
        return text


def _kb_data_dir() -> str:
    return settings.kb_data_dir


@router.get("/status")
def kb_status() -> dict[str, Any]:
    stats = kb_store.get_stats(data_dir=_kb_data_dir())
    cursor_check = check_cursor_api()
    if kb_sdk_agent.sdk_installed():
        kb_sdk_agent.sdk_usable(probe=True)
    sdk_check = kb_sdk_agent.sdk_status()
    backend_mode = (settings.kb_agent_backend or "auto").strip().lower()
    cursor_ready = bool(cursor_check.get("ok")) or bool(sdk_check.get("ok"))
    return {
        **stats,
        "cursor_configured": bool(settings.cursor_api_key),
        "cursor_api_available": bool(cursor_check.get("ok")),
        "cursor_api_check": cursor_check,
        "cursor_sdk_installed": kb_sdk_agent.sdk_installed(),
        "cursor_sdk_check": sdk_check,
        "cursor_sdk_available": cursor_ready,  # legacy: REST or SDK usable
        "kb_agent_backend": backend_mode,
        "cursor_backend": backend_mode if backend_mode != "auto" else "auto (sdk→rest)",
        "embedding_model": settings.kb_embedding_model,
        "openai_configured": bool(settings.openai_api_key),
        "fallback_openai": settings.kb_fallback_openai,
    }


@router.get("/documents")
def kb_documents(
    tag: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    return kb_store.list_documents(tag=tag, page=page, page_size=page_size, data_dir=_kb_data_dir())


@router.delete("/documents/{doc_id}")
def kb_delete_document(doc_id: str) -> dict[str, Any]:
    ok = kb_store.delete_document(doc_id, data_dir=_kb_data_dir())
    if not ok:
        raise HTTPException(status_code=404, detail="document not found")
    return {"deleted": True, "id": doc_id}


@router.post("/upload")
async def kb_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    raw = await file.read()
    try:
        return kb_ingest.ingest_upload(
            raw,
            file.filename or "upload.txt",
            mime=file.content_type,
            kb_data_dir=_kb_data_dir(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sync-project")
def kb_sync_project(
    data_dir: str = "data",
    docs_dir: str = "docs",
) -> dict[str, Any]:
    return kb_ingest.scan_project(
        data_dir=data_dir,
        docs_dir=docs_dir,
        kb_data_dir=_kb_data_dir(),
    )


@router.post("/chat")
def kb_chat_route(body: ChatRequest):
    try:
        message = body.resolved_message()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.stream:
        return StreamingResponse(
            kb_chat.chat_stream(
                message,
                session_id=body.session_id,
                top_k=body.top_k,
                tags=body.tags,
                data_dir=_kb_data_dir(),
            ),
            media_type="text/event-stream",
        )
    try:
        return kb_chat.chat(
            message,
            session_id=body.session_id,
            top_k=body.top_k,
            tags=body.tags,
            data_dir=_kb_data_dir(),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/chat/sessions")
def kb_sessions(limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    items = kb_store.list_sessions(limit=limit, data_dir=_kb_data_dir())
    return {"items": items, "count": len(items)}


@router.get("/chat/sessions/{session_id}")
def kb_session_detail(session_id: str) -> dict[str, Any]:
    session = kb_store.get_session(session_id, data_dir=_kb_data_dir())
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    messages = kb_store.list_messages(session_id, data_dir=_kb_data_dir())
    return {"session": session, "messages": messages}
