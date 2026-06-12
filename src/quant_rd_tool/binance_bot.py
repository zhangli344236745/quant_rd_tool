"""Binance spot trading bot via ccxt (dry-run by default).

Brings the spot bot to parity with the perp bot's risk controls:
- enhanced multi-timeframe signal with volatility/volume gates,
- ATR / risk-fraction position sizing (no leverage),
- soft stop-loss / take-profit tracked in a per-symbol state file,
- per-bar dedup so a signal only acts once per closed candle,
- JSONL telemetry, and
- a paper-trading mode that simulates fills and tracks P&L.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_analyzer import analyze_crypto_ohlcv, derive_trading_signal
from quant_rd_tool.crypto_paper_trading import (
    PaperAccount,
    apply_action,
    check_soft_protection,
    compute_performance,
)
from quant_rd_tool.crypto_signal import build_enhanced_signal, higher_timeframe_for
from quant_rd_tool.perp_risk import (
    compute_atr,
    compute_sl_tp_prices,
    compute_sl_tp_prices_atr,
    resolve_open_notional,
)
from quant_rd_tool.perp_telemetry import append_jsonl, daily_log_path
from quant_rd_tool.trading_state import TradingState

logger = logging.getLogger(__name__)

BotAction = Literal["buy", "sell", "hold"]


@dataclass
class BotConfig:
    symbol: str = "BTC"
    quote: str = "USDT"
    timeframe: str = "1d"
    ohlcv_limit: int = 200
    quote_amount: float = 50.0
    min_base_sell: float = 0.0001
    dry_run: bool = True
    testnet: bool = False
    exchange_id: cxt.ExchangeId = "binance"
    api_key: str | None = None
    api_secret: str | None = None

    # --- Risk / sizing ---
    sizing_mode: Literal["fixed", "atr", "hybrid"] = "hybrid"
    risk_fraction: float = 0.5  # fraction of quote_amount budget at full confidence
    min_signal_confidence: float = 0.0
    atr_period: int = 14
    use_atr_sl_tp: bool = True
    sl_pct: float = 0.03
    tp_pct: float = 0.06
    sl_atr: float = 1.5
    tp_atr: float = 2.5

    # --- Signal enhancement ---
    use_enhanced_signal: bool = True
    require_htf_confirm: bool = True
    require_volume_confirm: bool = False
    min_atr_pct: float = 0.0
    max_atr_pct: float = 0.0
    volume_min_ratio: float = 1.0

    # --- Paper trading ---
    paper_mode: bool = False
    paper_initial_cash: float = 10_000.0
    fee_pct: float = 0.001
    slippage_pct: float = 0.0005

    # --- State / telemetry ---
    state_dir: str = "data/crypto/spot_state"
    telemetry_enabled: bool = True
    telemetry_log_dir: str = "data/crypto/spot_logs"


@dataclass
class SpotProtectionState:
    """Soft SL/TP + last-seen bar for the live spot position."""

    entry_price: float = 0.0
    sl_price: float | None = None
    tp_price: float | None = None

    @staticmethod
    def load(path: str | Path) -> SpotProtectionState:
        p = Path(path)
        if not p.exists():
            return SpotProtectionState()
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
        return SpotProtectionState(
            entry_price=float(data.get("entry_price") or 0.0),
            sl_price=data.get("sl_price"),
            tp_price=data.get("tp_price"),
        )

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "entry_price": self.entry_price,
            "sl_price": self.sl_price,
            "tp_price": self.tp_price,
        }
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class BinanceBot:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._pair = cxt.to_ccxt_symbol(config.symbol, config.quote)
        self._base = self._pair.split("/")[0]
        sym = config.symbol.upper()
        self._state_path = Path(config.state_dir) / f"spot_state_{sym}.json"
        self._protection_path = Path(config.state_dir) / f"spot_protection_{sym}.json"
        self._paper_path = Path(config.state_dir) / f"spot_paper_{sym}.json"

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

    def _fetch_base_df(self):
        return cxt.fetch_ohlcv(
            self.config.symbol,
            timeframe=self.config.timeframe,
            limit=self.config.ohlcv_limit,
            exchange_id=self.config.exchange_id,
        )

    def _fetch_htf_df(self):
        htf = higher_timeframe_for(self.config.timeframe)
        try:
            return cxt.fetch_ohlcv(
                self.config.symbol,
                timeframe=htf,
                limit=120,
                exchange_id=self.config.exchange_id,
            )
        except Exception as e:
            logger.warning("HTF fetch failed for %s %s: %s", self.config.symbol, htf, e)
            return None

    def fetch_signal(
        self, *, use_ml: bool = False, data_dir: str = "data/crypto"
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

        df = self._fetch_base_df()
        analysis = analyze_crypto_ohlcv(df)
        if self.config.use_enhanced_signal:
            htf_df = self._fetch_htf_df()
            signal = build_enhanced_signal(
                df,
                htf_df,
                timeframe=self.config.timeframe,
                atr_period=self.config.atr_period,
                min_atr_pct=self.config.min_atr_pct,
                max_atr_pct=self.config.max_atr_pct,
                volume_min_ratio=self.config.volume_min_ratio,
                require_htf_confirm=self.config.require_htf_confirm,
                require_volume_confirm=self.config.require_volume_confirm,
            )
        else:
            signal = derive_trading_signal(analysis)
        return {
            "pair": self._pair,
            "analysis": analysis,
            "signal": signal,
            "ohlcv_bars": len(df),
            "bar_end": str((analysis.get("period") or {}).get("end") or ""),
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

    # --- sizing & protection -------------------------------------------------

    def _atr_value(self, df) -> float | None:
        try:
            return compute_atr(df, period=self.config.atr_period)
        except Exception:
            return None

    def _resolve_sizing(
        self, *, free_quote: float, confidence: float, ref_price: float, atr: float | None
    ):
        mode_map = {"fixed": "leverage_fraction", "atr": "atr", "hybrid": "hybrid"}
        sizing = resolve_open_notional(
            mode=mode_map.get(self.config.sizing_mode, "hybrid"),  # type: ignore[arg-type]
            free_usdt=float(free_quote),
            risk_fraction=float(self.config.risk_fraction),
            confidence=float(confidence),
            ref_price=float(ref_price) if ref_price > 0 else 1.0,
            leverage=1.0,
            atr=atr,
            sl_atr=float(self.config.sl_atr),
            min_conf=float(self.config.min_signal_confidence),
        )
        # Spot budget cap: never exceed the configured per-trade quote amount.
        sizing["notional_usdt"] = min(
            float(sizing["notional_usdt"]), float(self.config.quote_amount)
        )
        return sizing

    def _sl_tp_for(self, *, ref_price: float, atr: float | None) -> tuple[float, float]:
        if self.config.use_atr_sl_tp and atr and atr > 0:
            return compute_sl_tp_prices_atr(
                side="long",
                ref_price=ref_price,
                atr=atr,
                sl_atr=self.config.sl_atr,
                tp_atr=self.config.tp_atr,
            )
        return compute_sl_tp_prices(
            side="long", ref_price=ref_price, sl_pct=self.config.sl_pct, tp_pct=self.config.tp_pct
        )

    def _mode_label(self) -> str:
        if self.config.paper_mode:
            return "paper"
        return "dry_run" if self.config.dry_run else "live"

    def _log_telemetry(self, result: dict[str, Any], *, error: BaseException | None = None) -> None:
        if not self.config.telemetry_enabled:
            return
        try:
            record = {
                "ts": datetime.now(UTC).isoformat(),
                "symbol": self.config.symbol,
                "pair": self._pair,
                "mode": self._mode_label(),
                "action": (result.get("signal") or {}).get("action"),
                "message": result.get("message"),
                "error": str(error) if error else None,
            }
            append_jsonl(daily_log_path(self.config.telemetry_log_dir), record)
        except Exception as e:
            logger.debug("spot telemetry skipped: %s", e)

    # --- run -----------------------------------------------------------------

    def run_once(self) -> dict[str, Any]:
        if self.config.paper_mode:
            return self._run_paper()
        return self._run_live_or_dry()

    def _run_paper(self) -> dict[str, Any]:
        ctx = self.fetch_signal()
        signal = ctx["signal"]
        action: BotAction = signal["action"]
        df = self._fetch_base_df()
        price = float(df["close"].iloc[-1])
        atr = self._atr_value(df)
        bar_end = ctx.get("bar_end") or ""

        acc = PaperAccount.load(
            self._paper_path,
            symbol=self.config.symbol,
            quote=self.config.quote,
            initial_cash=self.config.paper_initial_cash,
        )
        acc.fee_pct = self.config.fee_pct
        acc.slippage_pct = self.config.slippage_pct

        result: dict[str, Any] = {
            "mode": "paper",
            "pair": self._pair,
            "signal": signal,
            "price": price,
            "bar_end": bar_end,
            "protection": None,
            "order": None,
        }

        protection = check_soft_protection(acc, price=price, ts=bar_end or None)
        if protection:
            result["protection"] = protection

        state = TradingState.load(self._state_path)
        traded_this_bar = bool(bar_end) and bar_end == state.last_seen_bar_end
        if traded_this_bar:
            result["message"] = "已处理过该周期信号（bar_end 去重），仅更新净值"
            apply_action(acc, action="hold", price=price, ts=bar_end or None)
        else:
            target = None
            sl = tp = None
            if action == "buy" and acc.position.base_amount <= 0:
                sizing = self._resolve_sizing(
                    free_quote=acc.cash,
                    confidence=float(signal.get("confidence") or 0.0),
                    ref_price=price,
                    atr=atr,
                )
                target = sizing["notional_usdt"]
                sl, tp = self._sl_tp_for(ref_price=price, atr=atr)
                result["sizing"] = sizing
            out = apply_action(
                acc, action=action, price=price, ts=bar_end or None,
                target_quote_amount=target, sl_price=sl, tp_price=tp,
            )
            result["order"] = out["order"]
            if bar_end:
                state.last_seen_bar_end = bar_end
                state.last_action = action
                state.save(self._state_path)
            result["message"] = "纸面交易已更新"

        acc.save(self._paper_path)
        result["performance"] = compute_performance(acc)
        result["position"] = {
            "base_amount": acc.position.base_amount,
            "entry_price": acc.position.entry_price,
            "sl_price": acc.position.sl_price,
            "tp_price": acc.position.tp_price,
        }
        self._log_telemetry(result)
        return result

    def _run_live_or_dry(self) -> dict[str, Any]:
        ctx = self.fetch_signal()
        signal = ctx["signal"]
        action: BotAction = signal["action"]
        df = self._fetch_base_df()
        price = float(df["close"].iloc[-1])
        atr = self._atr_value(df)
        bar_end = ctx.get("bar_end") or ""

        result: dict[str, Any] = {
            "dry_run": self.config.dry_run,
            "testnet": self.config.testnet,
            "pair": self._pair,
            "signal": signal,
            "analysis_summary": ctx["analysis"]["price"],
            "price": price,
            "bar_end": bar_end,
            "order": None,
            "protection": None,
            "balance_before": None,
        }

        if self.config.dry_run:
            sl, tp = self._sl_tp_for(ref_price=price, atr=atr) if action == "buy" else (None, None)
            sizing = None
            if action == "buy":
                sizing = self._resolve_sizing(
                    free_quote=self.config.quote_amount,
                    confidence=float(signal.get("confidence") or 0.0),
                    ref_price=price,
                    atr=atr,
                )
            result["sizing"] = sizing
            result["order"] = self._plan_order(action, sizing=sizing, sl=sl, tp=tp)
            result["message"] = "dry-run：未向交易所下单"
            self._log_telemetry(result)
            return result

        # Live: dedup per bar, soft SL/TP first, then act.
        state = TradingState.load(self._state_path)
        result["balance_before"] = self.fetch_balance()
        prot = SpotProtectionState.load(self._protection_path)

        balance = result["balance_before"]
        protection_out = self._check_live_protection(prot, price=price, balance=balance)
        if protection_out and protection_out.get("triggered"):
            result["protection"] = protection_out
            result["message"] = f"软保护触发（{protection_out['triggered']}）已卖出"
            self._log_telemetry(result)
            return result

        if bar_end and bar_end == state.last_seen_bar_end:
            result["message"] = "已处理过该周期信号（bar_end 去重），跳过"
            result["skipped_dedup"] = True
            self._log_telemetry(result)
            return result

        order = self._execute_order(action, balance, price=price, atr=atr, prot=prot)
        result["order"] = order
        result["message"] = "已提交订单" if order else "无下单（hold 或余额不足）"
        if bar_end:
            state.last_seen_bar_end = bar_end
            state.last_action = action
            state.save(self._state_path)
        self._log_telemetry(result)
        return result

    def _plan_order(
        self,
        action: BotAction,
        *,
        sizing: dict[str, Any] | None = None,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict[str, Any] | None:
        cfg = self.config
        if action == "hold":
            return {"side": "hold", "status": "skipped"}
        if action == "buy":
            return {
                "side": "buy",
                "type": "market",
                "symbol": self._pair,
                "quote_amount": (sizing or {}).get("notional_usdt") or cfg.quote_amount,
                "sl_price": sl,
                "tp_price": tp,
                "sizing": sizing,
                "status": "planned",
            }
        return {
            "side": "sell",
            "type": "market",
            "symbol": self._pair,
            "amount": "all_available_base",
            "status": "planned",
        }

    def _check_live_protection(
        self, prot: SpotProtectionState, *, price: float, balance: dict[str, float]
    ) -> dict[str, Any] | None:
        base_amt = balance.get(self._base, 0)
        if base_amt < self.config.min_base_sell or prot.entry_price <= 0:
            return None
        hit: str | None = None
        if prot.sl_price is not None and price <= prot.sl_price:
            hit = "stop_loss"
        elif prot.tp_price is not None and price >= prot.tp_price:
            hit = "take_profit"
        if not hit:
            return {"triggered": None, "sl_price": prot.sl_price, "tp_price": prot.tp_price}
        ex = self._exchange(authenticated=True)
        try:
            order = ex.create_order(self._pair, "market", "sell", base_amt)
        finally:
            try:
                ex.close()
            except Exception:
                pass
        SpotProtectionState().save(self._protection_path)
        return {"triggered": hit, "close_order_id": order.get("id")}

    def _execute_order(
        self,
        action: BotAction,
        balance: dict[str, float],
        *,
        price: float,
        atr: float | None,
        prot: SpotProtectionState,
    ) -> dict[str, Any] | None:
        if action == "hold":
            return None

        ex = self._exchange(authenticated=True)
        cfg = self.config
        try:
            if action == "buy":
                usdt = balance.get("USDT", 0)
                sizing = self._resolve_sizing(
                    free_quote=min(cfg.quote_amount, usdt * 0.99),
                    confidence=1.0,
                    ref_price=price,
                    atr=atr,
                )
                cost = min(float(sizing["notional_usdt"]), usdt * 0.99)
                if cost < 10:
                    logger.warning("USDT 余额不足，跳过买入")
                    return None
                order = ex.create_order(self._pair, "market", "buy", 0, None, {"cost": cost})
                sl, tp = self._sl_tp_for(ref_price=price, atr=atr)
                prot.entry_price = price
                prot.sl_price = sl
                prot.tp_price = tp
                prot.save(self._protection_path)
            else:
                base_amt = balance.get(self._base, 0)
                if base_amt < cfg.min_base_sell:
                    logger.warning("基础币余额不足，跳过卖出")
                    return None
                order = ex.create_order(self._pair, "market", "sell", base_amt)
                SpotProtectionState().save(self._protection_path)
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

    def paper_performance(self) -> dict[str, Any]:
        acc = PaperAccount.load(
            self._paper_path,
            symbol=self.config.symbol,
            quote=self.config.quote,
            initial_cash=self.config.paper_initial_cash,
        )
        return {
            "symbol": self.config.symbol,
            "performance": compute_performance(acc),
            "trades": acc.trades[-50:],
            "equity_curve": acc.equity_curve[-200:],
        }

    def reset_paper(self) -> dict[str, Any]:
        for p in (self._paper_path, self._state_path):
            Path(p).unlink(missing_ok=True)
        return {"reset": True, "symbol": self.config.symbol}

    def run_forever(self, interval_minutes: int = 60) -> None:
        logger.info("Spot bot started: %s interval=%sm", self._pair, interval_minutes)
        while True:
            started = time.time()
            try:
                self.run_once()
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.exception("Spot bot cycle failed")
            elapsed = time.time() - started
            time.sleep(max(interval_minutes * 60 - elapsed, 5))
