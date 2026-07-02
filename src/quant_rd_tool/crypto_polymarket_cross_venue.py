"""Match crypto-themed Polymarket ↔ Kalshi pairs and compare implied probabilities."""

from __future__ import annotations

import json
import re
from typing import Any

DEFAULT_MATCH_THRESHOLD = 0.6


def _token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def keyword_overlap_score(text_a: str, text_b: str, keywords: list[str]) -> float:
    ta = _token_set(text_a)
    tb = _token_set(text_b)
    if not ta or not tb:
        return 0.0
    kw_hits = sum(1 for k in keywords if k.lower() in ta and k.lower() in tb)
    if kw_hits == 0:
        return 0.0
    union = len(ta | tb) or 1
    jaccard = len(ta & tb) / union
    return min(1.0, kw_hits * 0.35 + jaccard * 0.65)


def compare_implied_prob(poly_yes: float | None, kalshi_yes: float | None) -> dict[str, Any]:
    if poly_yes is None or kalshi_yes is None:
        return {
            "prob_spread_bps": None,
            "poly_yes": poly_yes,
            "kalshi_yes": kalshi_yes,
            "arb_hint": "数据不足，无法比较跨所隐含概率。",
        }
    spread_bps = round((float(poly_yes) - float(kalshi_yes)) * 10_000, 2)
    hint = "两所定价接近。"
    if abs(spread_bps) >= 300:
        side = "Polymarket" if spread_bps > 0 else "Kalshi"
        hint = f"{side} YES 定价更高约 {abs(spread_bps):.0f} bps，仅供研究，勿盲目跨所套利。"
    return {
        "prob_spread_bps": spread_bps,
        "poly_yes": round(float(poly_yes), 4),
        "kalshi_yes": round(float(kalshi_yes), 4),
        "arb_hint": hint,
    }


def match_crypto_pair(
    poly_market: dict[str, Any],
    kalshi_markets: list[dict[str, Any]],
    *,
    keywords: list[str],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> dict[str, Any] | None:
    pq = str(poly_market.get("question") or "")
    best: tuple[float, dict[str, Any]] | None = None
    for km in kalshi_markets:
        kt = str(km.get("title") or "")
        sc = keyword_overlap_score(pq, kt, keywords)
        if sc >= threshold and (best is None or sc > best[0]):
            best = (sc, km)
    if not best:
        return None
    sc, km = best
    cmp = compare_implied_prob(
        poly_market.get("implied_prob_yes"),
        km.get("implied_prob_yes"),
    )
    return {
        "match_score": round(sc, 4),
        "poly": {
            "condition_id": poly_market.get("condition_id"),
            "question": poly_market.get("question"),
            "implied_prob_yes": poly_market.get("implied_prob_yes"),
            "market_url": poly_market.get("market_url"),
        },
        "kalshi": {
            "ticker": km.get("ticker"),
            "title": km.get("title"),
            "implied_prob_yes": km.get("implied_prob_yes"),
        },
        **cmp,
    }


def find_cross_venue_pairs(
    base: str,
    poly_markets: list[dict[str, Any]],
    kalshi_markets: list[dict[str, Any]],
    *,
    keywords: list[str] | None = None,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
    persist: bool = False,
) -> list[dict[str, Any]]:
    from quant_rd_tool.crypto_polymarket_context import keywords_for_symbol

    kw = keywords or keywords_for_symbol(base)
    pairs: list[dict[str, Any]] = []
    for pm in poly_markets:
        pair = match_crypto_pair(pm, kalshi_markets, keywords=kw, threshold=threshold)
        if pair:
            pair["base"] = base.upper()
            pairs.append(pair)
            if persist:
                append_cross_venue_history(pair)
    pairs.sort(key=lambda x: abs(float(x.get("prob_spread_bps") or 0)), reverse=True)
    return pairs


def append_cross_venue_history(pair: dict[str, Any]) -> None:
    from quant_rd_tool.crypto_polymarket_arb import POLYMARKET_DIR
    from quant_rd_tool.time_util import now_iso

    path = POLYMARKET_DIR / "cross_venue_history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "ts": now_iso(),
        "base": pair.get("base"),
        "condition_id": (pair.get("poly") or {}).get("condition_id"),
        "kalshi_ticker": (pair.get("kalshi") or {}).get("ticker"),
        "prob_spread_bps": pair.get("prob_spread_bps"),
        "poly_yes": pair.get("poly_yes"),
        "kalshi_yes": pair.get("kalshi_yes"),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(doc, ensure_ascii=False) + "\n")


def load_cross_venue_history(*, hours: float = 168.0, limit: int = 200) -> list[dict[str, Any]]:
    from datetime import UTC, datetime, timedelta

    from quant_rd_tool.crypto_polymarket_arb import POLYMARKET_DIR

    path = POLYMARKET_DIR / "cross_venue_history.jsonl"
    if not path.is_file():
        return []
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        ts = doc.get("ts")
        if ts:
            try:
                parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if parsed < cutoff:
                    continue
            except ValueError:
                pass
        out.append(doc)
    out.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return out[:limit]


def build_cross_venue_report(
    base: str,
    *,
    max_markets: int = 10,
    persist: bool = False,
    http_get: Any = None,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_kalshi_data import fetch_crypto_markets
    from quant_rd_tool.crypto_polymarket_context import fetch_polymarket_context, keywords_for_symbol

    sym = base.strip().upper() or "BTC"
    pm = fetch_polymarket_context(sym, max_markets=max_markets, http_get=http_get)
    markets = pm.get("markets") or []
    kw = keywords_for_symbol(sym)
    kalshi = fetch_crypto_markets(sym, limit=30, http_get=http_get)
    pairs = find_cross_venue_pairs(sym, markets, kalshi, keywords=kw, persist=persist)
    return {
        "base": sym,
        "polymarket_enabled": pm.get("enabled"),
        "polymarket_markets": len(markets),
        "pairs": pairs,
        "kalshi_count": len(kalshi),
        "top_market": pm.get("top_market"),
    }


def detect_bases_in_scan(items: list[dict[str, Any]]) -> list[str]:
    from quant_rd_tool.crypto_polymarket_context import CRYPTO_SYMBOL_KEYWORDS, score_market_relevance

    found: set[str] = set()
    for row in items:
        m = {"question": row.get("question"), "slug": row.get("slug"), "volume24hr": row.get("volume24hr")}
        for base, kws in CRYPTO_SYMBOL_KEYWORDS.items():
            if score_market_relevance(m, kws) > 0:
                found.add(base)
    if not found:
        return ["BTC", "ETH"]
    order = ["BTC", "ETH", "SOL", "BNB"]
    return [b for b in order if b in found] or sorted(found)
