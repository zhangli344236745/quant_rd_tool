"""Binance / ccxt connectivity self-check before scheduled sync."""

from __future__ import annotations

import time
from typing import Any

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.config import settings

_CONNECTIVITY_HINTS = [
    "在 .env 配置 HTTP_PROXY / HTTPS_PROXY（例如本地代理 127.0.0.1:7890）",
    "或设置 BINANCE_API_BASE=https://api1.binance.com（也可试 api2 / api3）",
    "先运行: uv run quant-rd crypto ping",
    "确认本机可访问 Binance（防火墙/VPN/地区限制）",
]


def check_connectivity(
    exchange_id: cxt.ExchangeId = "binance",
    *,
    test_ohlcv: bool = True,
    symbol: str = "BTC",
    timeframe: str = "5m",
) -> dict[str, Any]:
    """
    Probe ccxt → Binance: load_markets (exchangeInfo) and optional OHLCV sample.

    Returns a structured report suitable for CLI / API.
    """
    api_base = settings.binance_api_base if exchange_id == "binance" else None
    report: dict[str, Any] = {
        "ok": False,
        "exchange": exchange_id,
        "api_base": api_base or _default_api_base(exchange_id),
        "testnet": settings.binance_testnet if exchange_id == "binance" else False,
        "proxy": {
            "http": settings.http_proxy,
            "https": settings.https_proxy,
        },
        "steps": [],
        "hints": list(_CONNECTIVITY_HINTS),
    }

    ex = cxt.create_exchange(
        exchange_id,
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        testnet=settings.binance_testnet,
        api_base=api_base,
        http_proxy=settings.http_proxy,
        https_proxy=settings.https_proxy,
    )
    try:
        t0 = time.perf_counter()
        try:
            markets = ex.load_markets()
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            report["steps"].append(
                {
                    "name": "load_markets",
                    "ok": True,
                    "detail": f"exchangeInfo / markets loaded ({len(markets)} symbols)",
                    "latency_ms": elapsed_ms,
                }
            )
        except Exception as e:
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            report["steps"].append(
                {
                    "name": "load_markets",
                    "ok": False,
                    "detail": str(e),
                    "latency_ms": elapsed_ms,
                }
            )
            report["error"] = _friendly_error(e, exchange_id, api_base)
            return report

        if test_ohlcv:
            pair = cxt.to_ccxt_symbol(symbol)
            t1 = time.perf_counter()
            try:
                batch = ex.fetch_ohlcv(pair, timeframe=timeframe, limit=5)
                elapsed_ms = round((time.perf_counter() - t1) * 1000, 1)
                bars = len(batch or [])
                report["steps"].append(
                    {
                        "name": "fetch_ohlcv",
                        "ok": bars > 0,
                        "detail": f"{pair} {timeframe} sample bars={bars}",
                        "latency_ms": elapsed_ms,
                    }
                )
                if bars == 0:
                    report["error"] = f"OHLCV 为空: {pair}"
                    return report
            except Exception as e:
                elapsed_ms = round((time.perf_counter() - t1) * 1000, 1)
                report["steps"].append(
                    {
                        "name": "fetch_ohlcv",
                        "ok": False,
                        "detail": str(e),
                        "latency_ms": elapsed_ms,
                    }
                )
                report["error"] = _friendly_error(e, exchange_id, api_base)
                return report

        report["ok"] = all(s.get("ok") for s in report["steps"])
        report["summary"] = "连接正常，可执行定时拉取与分析。" if report["ok"] else "连接异常"
        return report
    finally:
        try:
            ex.close()
        except Exception:
            pass


def require_connectivity(
    exchange_id: cxt.ExchangeId = "binance",
    *,
    test_ohlcv: bool = True,
    symbol: str = "BTC",
    timeframe: str = "5m",
) -> dict[str, Any]:
    """Raise ConnectionError with hints if connectivity check fails."""
    report = check_connectivity(
        exchange_id,
        test_ohlcv=test_ohlcv,
        symbol=symbol,
        timeframe=timeframe,
    )
    if report.get("ok"):
        return report
    msg = report.get("error") or "Binance/ccxt 连接失败"
    hints = "\n".join(f"  - {h}" for h in report.get("hints", []))
    raise ConnectionError(f"{msg}\n建议:\n{hints}")


def _default_api_base(exchange_id: str) -> str:
    if exchange_id == "binance":
        return "https://api.binance.com"
    return exchange_id


def _friendly_error(exc: Exception, exchange_id: str, api_base: str | None) -> str:
    raw = str(exc)
    base = api_base or _default_api_base(exchange_id)
    if "exchangeInfo" in raw or "load_markets" in raw.lower():
        return (
            f"无法访问 {exchange_id} 市场信息 (exchangeInfo)，当前 API: {base}。"
            f" 原始错误: {raw}"
        )
    if "timed out" in raw.lower() or "timeout" in raw.lower():
        return f"连接 {base} 超时。原始错误: {raw}"
    return f"ccxt 连接 {exchange_id} 失败: {raw}"
