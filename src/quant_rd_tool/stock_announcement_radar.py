"""A-share announcement / news radar for watchlist (rule-based scoring)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool import akshare_stocks as astk
from quant_rd_tool.watchlist import Watchlist

DEFAULT_DATA_DIR = "data/stocks"
MIN_SCORE = 40

KEYWORD_RULES: list[tuple[str, int]] = [
    ("立案", 90),
    ("调查", 85),
    ("退市", 90),
    ("业绩预增", 80),
    ("业绩预减", 78),
    ("预亏", 75),
    ("预盈", 70),
    ("减持", 72),
    ("增持", 65),
    ("回购", 60),
    ("重组", 68),
    ("并购", 65),
    ("停牌", 70),
    ("风险提示", 75),
    ("监管", 70),
    ("处罚", 82),
]


def radar_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / "announcements"


def items_path(data_dir: str | Path) -> Path:
    return radar_root(data_dir) / "items.jsonl"


def digest_path(data_dir: str | Path) -> Path:
    return radar_root(data_dir) / "latest_digest.json"


def state_path(data_dir: str | Path) -> Path:
    return radar_root(data_dir) / "state.json"


def _item_hash(code: str, title: str, published: str) -> str:
    raw = f"{code}|{title}|{published}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def score_text(text: str) -> tuple[int, list[str]]:
    if not text:
        return 0, []
    hits: list[str] = []
    score = 0
    for kw, pts in KEYWORD_RULES:
        if kw in text:
            hits.append(kw)
            score = max(score, pts)
    return score, hits


def _load_seen(data_dir: str | Path) -> set[str]:
    path = state_path(data_dir)
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("seen") or [])
    except Exception:
        return set()


def _save_seen(data_dir: str | Path, seen: set[str]) -> None:
    path = state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"seen": sorted(seen)[-5000:]}, ensure_ascii=False, indent=2), encoding="utf-8")


def append_items(data_dir: str | Path, rows: list[dict[str, Any]]) -> None:
    path = items_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_digest(data_dir: str | Path) -> dict[str, Any]:
    path = digest_path(data_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_digest(data_dir: str | Path, digest: dict[str, Any]) -> None:
    path = digest_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")


def tail_items(*, data_dir: str = DEFAULT_DATA_DIR, limit: int = 50) -> list[dict[str, Any]]:
    path = items_path(data_dir)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(rows) >= limit:
            break
    return rows


def _resolve_symbols(symbols: list[str] | None, *, use_watchlist: bool) -> list[str]:
    from quant_rd_tool.akshare_data import to_ak_code

    if use_watchlist or not symbols:
        items = Watchlist().list_items()
        codes = [str(it.get("code") or "").strip() for it in items if it.get("code")]
        if codes:
            return [to_ak_code(c) for c in codes]
    return [to_ak_code(s) for s in (symbols or []) if str(s).strip()]


def run_announcement_scan(
    *,
    data_dir: str = DEFAULT_DATA_DIR,
    symbols: list[str] | None = None,
    use_watchlist: bool = True,
    notice_limit: int = 15,
    min_score: int = MIN_SCORE,
) -> dict[str, Any]:
    """Scan notices (+ optional news) for watchlist/universe; persist scored items."""
    from quant_rd_tool.akshare_data import to_ak_code

    codes = _resolve_symbols(symbols, use_watchlist=use_watchlist)
    if not codes:
        return {
            "items_processed": 0,
            "items_new": 0,
            "symbols": [],
            "digest": load_digest(data_dir),
            "error": "无扫描标的（请配置自选或 symbols）",
        }

    seen = _load_seen(data_dir)
    new_rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    top: list[dict[str, Any]] = []

    for code in codes:
        try:
            notices = astk.fetch_stock_notices(code, limit=notice_limit)
        except Exception as e:
            errors.append({"code": code, "error": str(e)})
            continue
        for row in notices:
            title = str(row.get("公告标题") or row.get("title") or "")
            published = str(row.get("公告日期") or row.get("date") or "")
            body = str(row.get("公告内容") or row.get("content") or title)
            text = f"{title} {body}"
            score, hits = score_text(text)
            if score < min_score:
                continue
            h = _item_hash(code, title, published)
            if h in seen:
                continue
            seen.add(h)
            entry = {
                "ts": datetime.now(UTC).isoformat(),
                "code": to_ak_code(code),
                "title": title,
                "published": published,
                "score": score,
                "keywords": hits,
                "source": "notice",
                "category": row.get("公告类型") or row.get("category"),
            }
            new_rows.append(entry)
            top.append(entry)

    if new_rows:
        append_items(data_dir, new_rows)
        _save_seen(data_dir, seen)

    top.sort(key=lambda x: x.get("score", 0), reverse=True)
    digest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "symbols_scanned": len(codes),
        "items_new": len(new_rows),
        "top_items": top[:20],
        "errors": errors,
    }
    save_digest(data_dir, digest)
    return {
        "items_processed": len(codes),
        "items_new": len(new_rows),
        "symbols": codes,
        "digest": digest,
        "fetch_errors": errors,
    }


def codes_with_high_impact(
    data_dir: str = DEFAULT_DATA_DIR,
    *,
    min_score: int = 70,
    within_hours: int = 72,
) -> set[str]:
    """Return codes with recent high-score announcements (for screener filter)."""
    digest = load_digest(data_dir)
    codes: set[str] = set()
    for item in digest.get("top_items") or []:
        if int(item.get("score") or 0) < min_score:
            continue
        codes.add(str(item.get("code") or ""))
    if codes:
        return {c for c in codes if c}
    cutoff = datetime.now(UTC).timestamp() - within_hours * 3600
    for row in tail_items(data_dir=data_dir, limit=200):
        if int(row.get("score") or 0) < min_score:
            continue
        try:
            ts = datetime.fromisoformat(str(row.get("ts", "")).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts.timestamp() >= cutoff:
                codes.add(str(row.get("code") or ""))
        except Exception:
            codes.add(str(row.get("code") or ""))
    return {c for c in codes if c}


def match_notice_keyword(code: str, keyword: str, *, data_dir: str = DEFAULT_DATA_DIR) -> bool:
    if not keyword.strip():
        return True
    pat = re.compile(re.escape(keyword.strip()), re.I)
    for row in tail_items(data_dir=data_dir, limit=100):
        if str(row.get("code")) != str(code):
            continue
        if pat.search(str(row.get("title") or "")):
            return True
    return False
