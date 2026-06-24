"""JSONL items, digest, and dedupe state for crypto news."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SEEN_MAX = 5000


def news_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / "crypto" / "news"


def items_path(data_dir: str | Path) -> Path:
    return news_root(data_dir) / "items.jsonl"


def digest_path(data_dir: str | Path) -> Path:
    return news_root(data_dir) / "latest_digest.json"


def state_path(data_dir: str | Path) -> Path:
    return news_root(data_dir) / "state.json"


def url_hash(link: str) -> str:
    return hashlib.sha256(link.strip().encode()).hexdigest()


def _ensure_root(data_dir: str | Path) -> Path:
    root = news_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_state(data_dir: str | Path) -> dict[str, Any]:
    path = state_path(data_dir)
    if not path.is_file():
        return {"seen_url_hashes": [], "last_fetch": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"seen_url_hashes": [], "last_fetch": {}}
    if not isinstance(data.get("seen_url_hashes"), list):
        data["seen_url_hashes"] = []
    if not isinstance(data.get("last_fetch"), dict):
        data["last_fetch"] = {}
    return data


def _save_state(data_dir: str | Path, state: dict[str, Any]) -> None:
    _ensure_root(data_dir)
    state_path(data_dir).write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_seen_url(data_dir: str | Path, link_hash: str) -> bool:
    state = _load_state(data_dir)
    return link_hash in state.get("seen_url_hashes", [])


def mark_seen_url(data_dir: str | Path, link_hash: str) -> None:
    state = _load_state(data_dir)
    seen: list[str] = list(state.get("seen_url_hashes") or [])
    if link_hash not in seen:
        seen.append(link_hash)
    if len(seen) > _SEEN_MAX:
        seen = seen[-_SEEN_MAX:]
    state["seen_url_hashes"] = seen
    _save_state(data_dir, state)


def append_item(data_dir: str | Path, item: dict[str, Any]) -> None:
    _ensure_root(data_dir)
    path = items_path(data_dir)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    link = item.get("link")
    if link:
        mark_seen_url(data_dir, url_hash(str(link)))


def load_items(data_dir: str | Path, *, limit: int = 50) -> list[dict[str, Any]]:
    path = items_path(data_dir)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    items: list[dict[str, Any]] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(items) >= limit:
            break
    return list(reversed(items))


def save_digest(data_dir: str | Path, digest: dict[str, Any]) -> None:
    _ensure_root(data_dir)
    digest_path(data_dir).write_text(
        json.dumps(digest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_digest(data_dir: str | Path) -> dict[str, Any] | None:
    path = digest_path(data_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def empty_digest() -> dict[str, Any]:
    """Placeholder when no scan has run yet."""
    return {
        "generated_at": None,
        "top_items": [],
        "market_stance": "neutral",
        "items_scored": 0,
        "items_new": 0,
        "fetch_errors": [],
        "empty": True,
    }


def utc_now_iso() -> str:
    return now_iso()
