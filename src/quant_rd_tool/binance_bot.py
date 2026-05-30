"""Binance spot trading bot via ccxt (dry-run by default)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_analyzer import analyze_crypto_ohlcv, derive_trading_signal

logger = logging.getLogger(__name__)

BotAction = Literal["buy", "sell", "hold"]


@dataclass
class BotConfig:
    symbol: str = "BTC"
    quote: str = "USDT"
    timeframe: str = "1d"
    ohlcv_limit: int = 120
    quote_amount: float = 50.0
    min_base_sell: float = 0.0001
    dry_run: bool = True
    testnet: bool = False
    exchange_id: cxt.ExchangeId = "binance"
    api_key: str | None = None
    api_secret: str | None = None


class BinanceBot:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._pair = cxt.to_ccxt_symbol(config.symbol, config.quote)
        self._base = self._pair.split("/")[0]

    def _exchange(self, *, authenticated: bool = False):
        if authenticated and not (self.config.api_key and self.config.api_secret):
            msg = "实盘/查余额需要 BINANCE_API_KEY 与 BINANCE_API_SECRET"
            raise ValueError(msg)
        return cxt.create_exchange(
            self.config.exchange_id,
            api_key=self.config.api_key if authenticated else None,
            api_secret=self.config.api_secret if authenticated else None,
            testnet=self.config.testnet,
        )

    def fetch_signal(
        self,
        *,
        use_ml: bool = False,
        data_dir: str = "data/crypto",
    ) -> dict[str, Any]:
        if use_ml:
            from quant_rd_tool.crypto_analysis import analyze_crypto

            report = analyze_crypto(
                self.config.symbol,
                data_dir=data_dir,
                timeframe=self.config.timeframe,
                limit=self.config.ohlcv_limit,
                refresh=False,
                with_ml=True,
                exchange_id=self.config.exchange_id,
            )
            return {
                "pair": self._pair,
                "analysis": report["analysis"],
                "signal": report["combined_signal"],
                "technical_signal": report.get("technical_signal"),
                "ml_analysis": report.get("ml_analysis"),
                "ohlcv_bars": report["period"]["bars"],
            }

        df = cxt.fetch_ohlcv(
            self.config.symbol,
            timeframe=self.config.timeframe,
            limit=self.config.ohlcv_limit,
            exchange_id=self.config.exchange_id,
        )
        analysis = analyze_crypto_ohlcv(df)
        signal = derive_trading_signal(analysis)
        return {
            "pair": self._pair,
            "analysis": analysis,
            "signal": signal,
            "ohlcv_bars": len(df),
        }

    def fetch_balance(self) -> dict[str, Any]:
        ex = self._exchange(authenticated=True)
        try:
            bal = ex.fetch_balance()
            free = bal.get("free") or {}
            return {
                "USDT": float(free.get("USDT") or 0),
                self._base: float(free.get(self._base) or 0),
            }
        finally:
            try:
                ex.close()
            except Exception:
                pass

    def run_once(self) -> dict[str, Any]:
        """Evaluate signal and optionally place one spot market order."""
        ctx = self.fetch_signal()
        action: BotAction = ctx["signal"]["action"]
        result: dict[str, Any] = {
            "dry_run": self.config.dry_run,
            "testnet": self.config.testnet,
            "pair": self._pair,
            "signal": ctx["signal"],
            "analysis_summary": ctx["analysis"]["price"],
            "order": None,
            "balance_before": None,
        }

        if self.config.dry_run:
            result["order"] = self._plan_order(action)
            result["message"] = "dry-run：未向交易所下单"
            return result

        result["balance_before"] = self.fetch_balance()
        order = self._execute_order(action, result["balance_before"])
        result["order"] = order
        result["message"] = "已提交订单" if order else "无下单（hold 或余额不足）"
        return result

    def _plan_order(self, action: BotAction) -> dict[str, Any] | None:
        cfg = self.config
        if action == "hold":
            return {"side": "hold", "status": "skipped"}
        if action == "buy":
            return {
                "side": "buy",
                "type": "market",
                "symbol": self._pair,
                "quote_amount": cfg.quote_amount,
                "status": "planned",
            }
        return {
            "side": "sell",
            "type": "market",
            "symbol": self._pair,
            "amount": "all_available_base",
            "status": "planned",
        }

    def _execute_order(
        self,
        action: BotAction,
        balance: dict[str, float],
    ) -> dict[str, Any] | None:
        if action == "hold":
            return None

        ex = self._exchange(authenticated=True)
        cfg = self.config
        try:
            if action == "buy":
                usdt = balance.get("USDT", 0)
                cost = min(cfg.quote_amount, usdt * 0.99)
                if cost < 10:
                    logger.warning("USDT 余额不足，跳过买入")
                    return None
                order = ex.create_order(self._pair, "market", "buy", 0, None, {"cost": cost})
            else:
                base_amt = balance.get(self._base, 0)
                if base_amt < cfg.min_base_sell:
                    logger.warning("基础币余额不足，跳过卖出")
                    return None
                order = ex.create_order(self._pair, "market", "sell", base_amt)
            return {
                "id": order.get("id"),
                "side": order.get("side"),
                "symbol": order.get("symbol"),
                "amount": order.get("amount"),
                "cost": order.get("cost"),
                "status": order.get("status"),
                "raw": {k: order.get(k) for k in ("id", "side", "price", "average", "filled")},
            }
        finally:
            try:
                ex.close()
            except Exception:
                pass
