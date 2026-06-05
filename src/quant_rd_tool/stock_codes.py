"""A-share symbol normalization (no akshare / network deps — safe in .venv-zipline)."""

from __future__ import annotations


def to_qlib_code(symbol: str) -> str:
    """Convert bare code (600519) or qlib code (SH600519) to qlib instrument id."""
    s = symbol.strip().upper()
    if s.startswith(("SH", "SZ")):
        return s
    if s.startswith("6"):
        return f"SH{s}"
    return f"SZ{s}"


def to_ak_code(symbol: str) -> str:
    """Bare 6-digit code for akshare APIs."""
    s = symbol.strip().upper()
    if s.startswith("SH"):
        return s[2:]
    if s.startswith("SZ"):
        return s[2:]
    return s


def to_market_prefixed_symbol(symbol: str) -> str:
    """sh600519 / sz000001 for Sina & Tencent APIs."""
    return to_qlib_code(symbol).lower()
