"""Cursor Cloud Agent integration for knowledge base chat."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from quant_rd_tool.config import project_root, settings
from quant_rd_tool import kb_sdk_agent
from quant_rd_tool.kb_cloud_agent import (
    CursorCloudAgentClient,
    CursorCloudAgentError,
    cloud_agent_available,
    default_client,
    is_cloud_agent_id,
)
from quant_rd_tool.kb_search import ChunkHit

logger = logging.getLogger(__name__)

DISCLAIMER = "仅供参考，不构成投资建议。"

_CRYPTO_SYMBOL_RE = re.compile(
    r"\b(BTC|ETH|SOL|BNB|XRP|DOGE|ADA|AVAX|DOT|LINK|MATIC|LTC|BCH|UNI|ATOM)\b",
    re.I,
)
_STOCK_CODE_RE = re.compile(r"\b([036]\d{5})\b")

_SYSTEM_PREFIX = (
    "你是金融研究助手。仅基于提供的知识库片段与实时摘要回答问题，"
    "不要修改代码、不要创建 PR、不要执行 shell 命令。"
    "若信息不足请明确说明；引用时标注来源编号。\n\n"
)


@dataclass
class AgentResult:
    answer: str
    agent_id: str | None = None
    citations: list[dict[str, Any]] | None = None
    backend: str = "cloud_rest"


# Keep alias for existing imports
def _cursor_available() -> bool:
    return cloud_agent_available()


def get_crypto_analysis_summary(symbol: str) -> dict[str, Any]:
    from pathlib import Path

    sym = symbol.upper().replace("/", "").replace("USDT", "")
    root = project_root() / "data" / "crypto" / f"CRYPTO_{sym}"
    out: dict[str, Any] = {"symbol": sym, "available": False}
    json_path = root / "report.json"
    md_path = root / "report.md"
    if json_path.is_file():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            narrative = data.get("narrative") or {}
            out.update(
                {
                    "available": True,
                    "stance": narrative.get("stance") or data.get("combined_signal"),
                    "summary": narrative.get("summary"),
                    "generated_at": data.get("generated_at"),
                    "path": str(json_path.relative_to(project_root())),
                }
            )
        except Exception as exc:
            out["error"] = str(exc)
    if md_path.is_file():
        md = md_path.read_text(encoding="utf-8", errors="replace")
        out["markdown_excerpt"] = md[:2000]
        out.setdefault("path", str(md_path.relative_to(project_root())))
        out["available"] = True
    return out


def get_stock_report_summary(code: str) -> dict[str, Any]:
    from quant_rd_tool.report_index import latest_report

    try:
        rep = latest_report(code, data_dir=project_root() / "data" / "stocks")
        return {
            "available": True,
            "code": rep.get("qlib_code") or code,
            "stance": rep.get("stance"),
            "summary": rep.get("summary"),
            "generated_at": rep.get("generated_at"),
            "markdown_excerpt": (rep.get("markdown") or "")[:2000],
        }
    except Exception as exc:
        return {"available": False, "code": code, "error": str(exc)}


def enrich_prompt_with_live_data(user_message: str, prompt: str) -> str:
    extras: list[str] = []
    seen: set[str] = set()
    for m in _CRYPTO_SYMBOL_RE.finditer(user_message):
        sym = m.group(1).upper()
        if sym in seen:
            continue
        seen.add(sym)
        summary = get_crypto_analysis_summary(sym)
        if summary.get("available"):
            extras.append(f"### Crypto {sym}\n{json.dumps(summary, ensure_ascii=False)}")
    for m in _STOCK_CODE_RE.finditer(user_message):
        code = m.group(1)
        if code in seen:
            continue
        seen.add(code)
        summary = get_stock_report_summary(code)
        if summary.get("available"):
            extras.append(f"### A股 {code}\n{json.dumps(summary, ensure_ascii=False)}")
    if not extras:
        return prompt
    return prompt + "\n\n## 实时报告摘要\n" + "\n\n".join(extras)


def build_prompt(chunks: list[ChunkHit], user_message: str) -> str:
    ctx_lines = []
    for i, ch in enumerate(chunks, 1):
        src = ch.doc_path or ch.doc_title
        ctx_lines.append(f"[{i}] ({src})\n{ch.text}")
    context = "\n\n---\n\n".join(ctx_lines) if ctx_lines else "(无检索上下文)"
    body = (
        f"## 知识库片段\n{context}\n\n## 用户问题\n{user_message}"
    )
    prompt = _SYSTEM_PREFIX + body
    return enrich_prompt_with_live_data(user_message, prompt)


def _wait_agent_idle(client: CursorCloudAgentClient, agent_id: str, *, timeout: float = 60) -> None:
    from quant_rd_tool.kb_cloud_agent import _TERMINAL_STATUSES

    deadline = time.time() + timeout
    while time.time() < deadline:
        agent = client.get_agent(agent_id)
        latest_run_id = agent.get("latestRunId")
        if not latest_run_id:
            return
        run = client.get_run(agent_id, str(latest_run_id))
        status = str(run.get("status") or "").upper()
        if status in _TERMINAL_STATUSES:
            return
        time.sleep(2)
    raise CursorCloudAgentError(f"agent {agent_id} still busy after {timeout}s")


def _normalize_agent_id(agent_id: str | None) -> str | None:
    if not is_cloud_agent_id(agent_id):
        if agent_id:
            logger.warning("ignoring non-cloud agent_id %r; creating new cloud agent", agent_id)
        return None
    return agent_id


def _backend_order() -> list[str]:
    mode = (settings.kb_agent_backend or "auto").strip().lower()
    if mode == "sdk":
        return ["sdk"]
    if mode == "rest":
        return ["rest"]
    if kb_sdk_agent.sdk_usable():
        return ["sdk", "rest"]
    return ["rest"]


def _run_rest_chat(
    prompt: str,
    *,
    agent_id: str | None,
    client_factory: Callable[[], CursorCloudAgentClient] | None,
) -> AgentResult:
    factory = client_factory or default_client
    logger.info("kb chat via Cursor Cloud REST (agent_id=%s)", agent_id or "new")
    with factory() as client:
        aid, run_id = _start_run(client, prompt, agent_id=agent_id)
        answer = client.wait_for_run(aid, run_id)
        return AgentResult(answer=answer or "(无回复)", agent_id=aid, backend="cloud_rest")


def _start_run(
    client: CursorCloudAgentClient,
    prompt: str,
    *,
    agent_id: str | None,
) -> tuple[str, str]:
    agent_id = _normalize_agent_id(agent_id)
    if agent_id:
        try:
            run_id = client.create_run(agent_id, prompt)
            return agent_id, run_id
        except CursorCloudAgentError as exc:
            if exc.status_code == 409:
                logger.info("agent %s busy, waiting then retrying follow-up", agent_id)
                _wait_agent_idle(client, agent_id)
                run_id = client.create_run(agent_id, prompt)
                return agent_id, run_id
            if exc.status_code in {400, 404, 410}:
                logger.warning(
                    "follow-up on agent %s failed (%s); creating new cloud agent",
                    agent_id,
                    exc,
                )
            else:
                raise
    new_agent_id, run_id = client.create_agent(prompt)
    return new_agent_id, run_id


def run_agent_chat(
    message: str,
    *,
    session_id: str | None = None,
    agent_id: str | None = None,
    context_chunks: list[ChunkHit] | None = None,
    data_dir: str | None = None,
    agent_factory: Callable[..., Any] | None = None,
    client_factory: Callable[[], CursorCloudAgentClient] | None = None,
) -> AgentResult:
    del session_id, data_dir, agent_factory
    if not cloud_agent_available():
        raise RuntimeError("CURSOR_API_KEY not configured")

    prompt = build_prompt(context_chunks or [], message)
    errors: list[str] = []
    for backend in _backend_order():
        try:
            if backend == "sdk":
                answer, aid = kb_sdk_agent.run_sdk_chat(prompt, agent_id=agent_id)
                return AgentResult(answer=answer, agent_id=aid, backend="cloud_sdk")
            return _run_rest_chat(prompt, agent_id=agent_id, client_factory=client_factory)
        except Exception as exc:
            errors.append(f"{backend}: {exc}")
            if backend == "sdk":
                kb_sdk_agent.mark_sdk_unavailable(str(exc))
                if (settings.kb_agent_backend or "auto").strip().lower() == "auto":
                    logger.debug("KB SDK unavailable, falling back to REST: %s", exc)
                else:
                    logger.warning("KB sdk backend failed: %s", exc)
            else:
                logger.warning("KB %s backend failed: %s", backend, exc)
    raise RuntimeError("; ".join(errors) or "no cloud backend available")


@dataclass
class StreamChatResult:
    chunks: list[str]
    agent_id: str | None
    backend: str


def _stream_rest_chat(
    prompt: str,
    *,
    agent_id: str | None,
    client_factory: Callable[[], CursorCloudAgentClient] | None,
) -> tuple[list[str], str, str]:
    factory = client_factory or default_client
    logger.info("kb stream via Cursor Cloud REST (agent_id=%s)", agent_id or "new")
    with factory() as client:
        aid, run_id = _start_run(client, prompt, agent_id=agent_id)
        chunks: list[str] = []
        try:
            for piece in client.stream_run_text(aid, run_id):
                chunks.append(piece)
        except CursorCloudAgentError as exc:
            logger.warning("cloud stream failed (%s), falling back to poll", exc)
        if not chunks:
            text = client.wait_for_run(aid, run_id)
            if text and text != "(无回复)":
                chunks.append(text)
        return chunks, aid, "cloud_rest"


def stream_agent_chat(
    message: str,
    *,
    agent_id: str | None = None,
    context_chunks: list[ChunkHit] | None = None,
    data_dir: str | None = None,
    agent_factory: Callable[..., Any] | None = None,
    client_factory: Callable[[], CursorCloudAgentClient] | None = None,
) -> Iterator[str]:
    """Stream assistant text chunks; sets ``stream_agent_meta`` when complete."""
    del data_dir, agent_factory
    global stream_agent_meta
    if not cloud_agent_available():
        raise RuntimeError("CURSOR_API_KEY not configured")

    prompt = build_prompt(context_chunks or [], message)
    errors: list[str] = []
    for backend in _backend_order():
        try:
            if backend == "sdk":
                aid, text_iter = kb_sdk_agent.stream_sdk_chat(prompt, agent_id=agent_id)
                chunks: list[str] = []
                for piece in text_iter:
                    chunks.append(piece)
                    yield piece
                stream_agent_meta = StreamChatResult(
                    chunks=chunks,
                    agent_id=aid,
                    backend="cloud_sdk",
                )
                return
            chunks, aid, be = _stream_rest_chat(
                prompt, agent_id=agent_id, client_factory=client_factory
            )
            for piece in chunks:
                yield piece
            stream_agent_meta = StreamChatResult(chunks=chunks, agent_id=aid, backend=be)
            return
        except Exception as exc:
            errors.append(f"{backend}: {exc}")
            if backend == "sdk":
                kb_sdk_agent.mark_sdk_unavailable(str(exc))
                if (settings.kb_agent_backend or "auto").strip().lower() == "auto":
                    logger.debug("KB SDK stream unavailable, falling back to REST: %s", exc)
                else:
                    logger.warning("KB stream sdk backend failed: %s", exc)
            else:
                logger.warning("KB stream %s backend failed: %s", backend, exc)
    raise RuntimeError("; ".join(errors) or "no cloud backend available")


# Set by stream_agent_chat when the generator completes.
stream_agent_meta: StreamChatResult | None = None


def _stream_agent_chat_collect(
    message: str,
    *,
    agent_id: str | None = None,
    context_chunks: list[ChunkHit] | None = None,
    client_factory: Callable[[], CursorCloudAgentClient] | None = None,
) -> StreamChatResult:
    chunks = list(
        stream_agent_chat(
            message,
            agent_id=agent_id,
            context_chunks=context_chunks,
            client_factory=client_factory,
        )
    )
    return stream_agent_meta or StreamChatResult(chunks=chunks, agent_id=None, backend="cloud_rest")


def rag_only_answer(hits: list[ChunkHit], user_message: str) -> str:
    if not hits:
        return "未在知识库中找到相关内容。请先点击「同步项目数据」或上传文档。"
    lines = [f"根据知识库检索结果，关于「{user_message}」：", ""]
    for i, h in enumerate(hits[:5], 1):
        src = h.doc_path or h.doc_title
        lines.append(f"**[{i}] {src}**")
        lines.append(h.text[:600])
        lines.append("")
    lines.append("_（Cloud Agent 暂不可用，以上为检索摘要）_")
    return "\n".join(lines)


def fallback_openai_chat(message: str, *, context_chunks: list[ChunkHit] | None = None) -> str:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_api_base)
    prompt = build_prompt(context_chunks or [], message)
    resp = client.chat.completions.create(
        model=settings.chat_model,
        messages=[
            {"role": "system", "content": "你是金融研究助手。"},
            {"role": "user", "content": prompt},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def resolve_answer_with_fallback(
    message: str,
    *,
    hits: list[ChunkHit],
    agent_factory: Callable[..., Any] | None = None,
    agent_id: str | None = None,
    data_dir: str | None = None,
    client_factory: Callable[[], CursorCloudAgentClient] | None = None,
) -> tuple[str, str | None, str, str | None]:
    del agent_factory, data_dir
    cloud_error: str | None = None
    if cloud_agent_available():
        try:
            result = run_agent_chat(
                message,
                agent_id=agent_id,
                context_chunks=hits,
                client_factory=client_factory,
            )
            return result.answer, result.agent_id, result.backend, None
        except Exception as exc:
            cloud_error = str(exc)
            logger.warning("Cloud agent failed: %s", exc)
    if settings.kb_fallback_openai and settings.openai_api_key:
        try:
            return fallback_openai_chat(message, context_chunks=hits), None, "openai", cloud_error
        except Exception as exc:
            logger.warning("OpenAI fallback failed: %s", exc)
            if not cloud_error:
                cloud_error = str(exc)
    return rag_only_answer(hits, message), None, "rag", cloud_error


# Re-export for kb_search custom tool path (tests / future MCP)
def build_custom_tools(*, data_dir: str | None = None) -> dict[str, Any]:
    del data_dir
    return {}
