"""Cursor Python SDK integration for finance KB (official Agent / Run patterns).

Falls back to REST when the SDK bridge is unavailable. See:
https://cursor.com/docs/sdk/python
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

from quant_rd_tool.config import settings
from quant_rd_tool.kb_cloud_agent import is_cloud_agent_id

logger = logging.getLogger(__name__)

_SDK_AGENT_NAME = "Finance KB"
# Process-local: skip SDK after probe or runtime failure (bridge 502, etc.).
_sdk_disabled_reason: str | None = None
_sdk_probe_done = False


def sdk_installed() -> bool:
    try:
        import cursor_sdk  # noqa: F401

        return True
    except ImportError:
        return False


def check_sdk_api() -> dict[str, Any]:
    """Probe SDK (Cursor.me). May fail with bridge 502 even when REST works."""
    if not sdk_installed():
        return {
            "ok": False,
            "error": "cursor-sdk not installed (uv pip install 'quant-rd-tool[kb]')",
        }
    key = (settings.cursor_api_key or "").strip()
    if not key:
        return {"ok": False, "error": "CURSOR_API_KEY not configured"}
    try:
        from cursor_sdk import Cursor

        me = Cursor.me(api_key=key)
        if isinstance(me, dict):
            return {
                "ok": True,
                "user_email": me.get("userEmail"),
                "api_key_name": me.get("apiKeyName"),
            }
        return {
            "ok": True,
            "user_email": getattr(me, "user_email", None),
            "api_key_name": getattr(me, "api_key_name", None),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def mark_sdk_unavailable(reason: str) -> None:
    """Remember SDK is down for this process (auto mode skips SDK thereafter)."""
    global _sdk_disabled_reason, _sdk_probe_done
    _sdk_disabled_reason = reason.strip() or "sdk unavailable"
    _sdk_probe_done = True
    logger.info("Cursor SDK disabled for KB (using REST): %s", _sdk_disabled_reason[:240])


def reset_sdk_availability() -> None:
    """Clear cached SDK failure (tests / manual retry)."""
    global _sdk_disabled_reason, _sdk_probe_done
    _sdk_disabled_reason = None
    _sdk_probe_done = False


def sdk_usable(*, probe: bool = False) -> bool:
    """True when SDK is installed and not known-broken (bridge 502, etc.)."""
    global _sdk_disabled_reason, _sdk_probe_done
    if not sdk_installed():
        return False
    if _sdk_disabled_reason and not probe:
        return False
    if not _sdk_probe_done or probe:
        _sdk_probe_done = True
        result = check_sdk_api()
        if not result.get("ok"):
            mark_sdk_unavailable(str(result.get("error") or "sdk probe failed"))
            return False
        _sdk_disabled_reason = None
    return True


def sdk_status() -> dict[str, Any]:
    """Status payload for /kb/status (uses cached probe when available)."""
    if not sdk_installed():
        return {
            "ok": False,
            "error": "cursor-sdk not installed (uv pip install 'quant-rd-tool[kb]')",
        }
    if _sdk_disabled_reason:
        return {"ok": False, "error": _sdk_disabled_reason}
    return check_sdk_api()


def _resume_options() -> dict[str, Any]:
    return {"api_key": settings.cursor_api_key}


def _create_kwargs() -> dict[str, Any]:
    from cursor_sdk import CloudAgentOptions

    # cursor-sdk 0.1.x: mode belongs on SendOptions, not Agent.create().
    return {
        "model": settings.kb_cursor_model,
        "api_key": settings.cursor_api_key,
        "name": _SDK_AGENT_NAME,
        # No repos: empty cloud workspace for RAG-in-prompt Q&A only.
        "cloud": CloudAgentOptions(),
    }


def _open_agent(agent_id: str | None):
    from cursor_sdk import Agent

    if is_cloud_agent_id(agent_id):
        return Agent.resume(agent_id, _resume_options())
    return Agent.create(**_create_kwargs())


def _send_with_busy_retry(agent: Any, prompt: str) -> Any:
    from cursor_sdk import AgentBusyError

    delays = (0.0, 2.0, 4.0)
    last_exc: Exception | None = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            return agent.send(prompt)
        except AgentBusyError as exc:
            last_exc = exc
            logger.info("SDK agent busy, retrying send (%s)", exc)
    if last_exc:
        raise last_exc
    raise RuntimeError("SDK send failed")


def run_sdk_chat(prompt: str, *, agent_id: str | None = None) -> tuple[str, str]:
    """Blocking chat via Agent.create / Agent.resume + run.text()."""
    if not sdk_installed():
        raise RuntimeError("cursor-sdk not installed")
    if not (settings.cursor_api_key or "").strip():
        raise RuntimeError("CURSOR_API_KEY not configured")

    logger.info("kb chat via Cursor Python SDK (agent_id=%s)", agent_id or "new")
    with _open_agent(agent_id) as agent:
        run = _send_with_busy_retry(agent, prompt)
        answer = (run.text() or "").strip() or "(无回复)"
        return answer, str(agent.agent_id)


def stream_sdk_chat(prompt: str, *, agent_id: str | None = None) -> tuple[str, Iterator[str]]:
    """Return (agent_id, text iterator). Keeps agent open until the iterator is exhausted."""
    if not sdk_installed():
        raise RuntimeError("cursor-sdk not installed")
    if not (settings.cursor_api_key or "").strip():
        raise RuntimeError("CURSOR_API_KEY not configured")

    logger.info("kb stream via Cursor Python SDK (agent_id=%s)", agent_id or "new")
    agent = _open_agent(agent_id)
    aid = str(agent.agent_id)
    run = _send_with_busy_retry(agent, prompt)

    def _iter() -> Iterator[str]:
        yielded = False
        try:
            try:
                for chunk in run.iter_text():
                    if chunk:
                        yielded = True
                        yield chunk
            except Exception as exc:
                logger.warning("SDK iter_text failed (%s), falling back to run.text()", exc)
            if not yielded:
                text = (run.text() or "").strip()
                if text and text != "(无回复)":
                    yield text
        finally:
            agent.close()

    return aid, _iter()
