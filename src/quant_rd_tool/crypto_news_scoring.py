"""Rule-based impact scoring for crypto/macro news items."""

from __future__ import annotations

import re
from typing import Any

CATEGORIES = ("macro", "regulation", "security", "market", "crypto_native")

HIGH_KEYWORDS: dict[str, tuple[str, ...]] = {
    "macro": (
        "fed",
        "federal reserve",
        "interest rate",
        "rate hike",
        "raises rates",
        "inflation",
        "fomc",
        "monetary policy",
        "recession",
        "gdp",
        "cpi",
        "employment",
        "treasury",
    ),
    "regulation": (
        "sec",
        "regulation",
        "lawsuit",
        "enforcement",
        "ban",
        "compliance",
        "etf approval",
        "etf",
    ),
    "security": (
        "hack",
        "exploit",
        "breach",
        "stolen",
        "vulnerability",
    ),
    "crypto_native": (
        "bitcoin",
        "ethereum",
        "crypto",
        "blockchain",
        "defi",
        "stablecoin",
    ),
    "market": (
        "market",
        "trading",
        "volume",
        "liquidation",
    ),
}

MEDIUM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "macro": ("economy", "jobs", "payroll", "yield", "bond"),
    "regulation": ("regulator", "policy", "fine", "settlement"),
    "security": ("audit", "security"),
    "crypto_native": ("altcoin", "token", "mining", "halving"),
    "market": ("rally", "selloff", "volatility"),
}

LOW_KEYWORDS: dict[str, tuple[str, ...]] = {
    "macro": ("central bank", "forecast"),
    "regulation": ("guidance", "framework"),
    "crypto_native": ("wallet", "exchange"),
    "market": ("price", "surge", "drop"),
}

SYMBOL_PATTERNS = {
    "BTC": re.compile(r"\b(btc|bitcoin)\b", re.I),
    "ETH": re.compile(r"\b(eth|ethereum)\b", re.I),
    "SOL": re.compile(r"\b(sol|solana)\b", re.I),
}

IMPACT_HINTS = {
    "macro": {"raises rates": "bearish", "rate hike": "bearish", "rate cut": "bullish", "inflation": "bearish"},
    "regulation": {"approval": "bullish", "approves": "bullish", "lawsuit": "bearish", "sues": "bearish", "ban": "bearish"},
    "security": {"hack": "bearish", "exploit": "bearish", "breach": "bearish"},
    "crypto_native": {"surge": "bullish", "inflows": "bullish", "outflows": "bearish"},
}


def _text_blob(item: dict[str, Any]) -> str:
    return f"{item.get('title', '')} {item.get('summary', '')}".lower()


def _detect_symbols(text: str) -> list[str]:
    found: list[str] = []
    for sym, pattern in SYMBOL_PATTERNS.items():
        if pattern.search(text):
            found.append(sym)
    return found


def _score_keywords(text: str) -> tuple[int, str, list[str]]:
    best_category = "market"
    best_score = 0
    matched: list[str] = []
    for category in CATEGORIES:
        cat_score = 0
        for kw in HIGH_KEYWORDS.get(category, ()):
            if kw in text:
                cat_score += 30
                matched.append(kw)
        for kw in MEDIUM_KEYWORDS.get(category, ()):
            if kw in text:
                cat_score += 15
                matched.append(kw)
        for kw in LOW_KEYWORDS.get(category, ()):
            if kw in text:
                cat_score += 5
                matched.append(kw)
        if cat_score > best_score:
            best_score = cat_score
            best_category = category
    return best_score, best_category, matched


def _impact_direction(text: str, category: str) -> str:
    hints = IMPACT_HINTS.get(category, {})
    for phrase, direction in hints.items():
        if phrase in text:
            return direction
    if category == "regulation" and ("approve" in text or "approval" in text):
        return "bullish"
    if category == "security":
        return "bearish"
    if category == "macro" and ("rate" in text or "inflation" in text):
        return "bearish"
    return "neutral"


def score_news_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return item enriched with score, category, symbols, impact_direction."""
    text = _text_blob(item)
    base_score, category, keywords = _score_keywords(text)
    symbols = _detect_symbols(text)
    score = base_score + (10 if symbols else 0)
    direction = _impact_direction(text, category)
    out = dict(item)
    out.update(
        {
            "score": score,
            "category": category,
            "symbols": symbols,
            "impact_direction": direction,
            "matched_keywords": keywords,
        }
    )
    return out


def rank_candidates(
    items: list[dict[str, Any]],
    *,
    min_score: int = 40,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Score items if needed, filter by min_score, return top N by score."""
    scored: list[dict[str, Any]] = []
    for item in items:
        if "score" not in item or "category" not in item:
            item = score_news_item(item)
        if item.get("score", 0) >= min_score:
            scored.append(item)
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    return scored[:top_n]
