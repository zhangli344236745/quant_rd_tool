"""Binance USDT-M perpetual trading bot via ccxt (dry-run by default)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_analysis import analyze_crypto
from quant_rd_tool.perp_exec import (
    apply_protection_policy_to_state,
    build_native_protection_params,
    decide_protection_policy,
    evaluate_soft_sl_tp,
    reconcile_native_protection,
    try_place_native_sl_tp,
)
from quant_rd_tool.perp_models import build_client_order_id
from quant_rd_tool.perp_risk import (
    CircuitBreakerState,
    SizingMode,
    apply_circuit_breaker_to_plan,
    compute_atr,
    resolve_open_notional,
    should_block_entries,
)
from quant_rd_tool.perp_state import PerpSymbolState
from quant_rd_tool.perp_telemetry import PerpTelemetry, TelemetryConfig
from quant_rd_tool.trading_state import TradingState

logger = logging.getLogger(__name__)

PerpAction = Literal["long", "short", "hold"]
PositionSide = Literal["long", "short", "flat"]
HoldBehavior = Literal["do_nothing", "close_position"]
TriggerSource = Literal["last", "mark"]


@dataclass
class PerpBotConfig:
    base: str = "BTC"
    quote: str = "USDT"
    timeframe: str = "5m"
    ohlcv_limit: int = 800
    interval_minutes: int = 10

    dry_run: bool = True
    testnet: bool = False

    exchange_id: cxt.ExchangeId = "binance"
    api_key: str | None = None
    api_secret: str | None = None

    leverage: int = 3
    usdt_risk_fraction: float = 0.20  # fraction of free USDT to allocate per position
    hold_behavior: HoldBehavior = "do_nothing"
    min_notional_usdt: float = 10.0
    position_epsilon: float = 1e-12
    sl_pct: float = 0.01
    tp_pct: float = 0.015
    sizing_mode: SizingMode = "hybrid"
    atr_period: int = 14
    sl_atr: float = 1.5
    tp_atr: float = 2.5
    use_atr_sl_tp: bool = True
    min_signal_confidence: float = 0.0
    use_native_protection: bool = True
    trigger_source: TriggerSource = "last"
    max_protection_failures: int = 3
    max_daily_loss_pct: float = 0.03  # 0 = disabled; block new entries when daily loss exceeds

    # Dedupe state to avoid repeated trades on same bar across restarts
    state_path: str = ""
    protection_state_path: str = ""

    # Optional override if your ccxt market symbol differs, e.g. "BTC/USDT:USDT"
    ccxt_symbol: str = ""

    telemetry_enabled: bool = True
    telemetry_log_dir: str = "data/crypto/perp_logs"


def _normalize_position_rows(
    rows: list[dict[str, Any]],
    *,
    position_epsilon: float,
) -> tuple[PositionSide, float]:
    if not rows:
        return "flat", 0.0
    if len(rows) != 1:
        raise ValueError("Multiple position rows detected (hedge/multi-leg not supported)")
    r = rows[0] or {}
    raw = r.get("contracts")
    if raw is None:
        info = r.get("info") or {}
        raw = info.get("positionAmt")
    amt = float(raw or 0.0)
    if abs(amt) <= position_epsilon:
        return "flat", 0.0
    if amt > 0:
        return "long", amt
    return "short", abs(amt)


def _calc_amount_from_notional(*, notional_usdt: float, price: float, amount_step: float) -> float:
    if price <= 0:
        raise ValueError("price must be positive")
    if amount_step <= 0:
        raise ValueError("amount_step must be positive")
    raw = float(notional_usdt) / float(price)
    steps = int(raw / amount_step)
    return round(steps * amount_step, 12)


def _decide_plan(
    *,
    position_side: PositionSide,
    target_side: PositionSide,
    hold_behavior: HoldBehavior,
) -> dict[str, bool]:
    if target_side == position_side:
        return {"close": False, "open": False}
    if target_side == "flat":
        if hold_behavior == "close_position" and position_side != "flat":
            return {"close": True, "open": False}
        return {"close": False, "open": False}
    if position_side != "flat" and target_side != position_side:
        return {"close": True, "open": True}
    return {"close": False, "open": True}


def _should_trade_bar(state: TradingState, *, bar_end: str) -> bool:
    return bool(bar_end) and bar_end != state.last_seen_bar_end


def _action_to_target(action: PerpAction) -> PositionSide:
    if action == "long":
        return "long"
    if action == "short":
        return "short"
    return "flat"


def _signal_confidence(signal: dict[str, Any] | None) -> float:
    if not signal:
        return 1.0
    raw = signal.get("confidence")
    if raw is None:
        return 1.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 1.0


class BinancePerpBot:
    def __init__(self, config: PerpBotConfig) -> None:
        self.config = config
        self._base_pair = cxt.to_ccxt_symbol(config.base, config.quote)  # "BTC/USDT"
        self._perp_pair = config.ccxt_symbol.strip() or f"{config.base}/{config.quote}:{config.quote}"
        self._state_path = Path(
            (config.state_path.strip() or f"data/crypto/perp_state_{config.base.upper()}.json")
        )
        self._protection_state_path = Path(
            (
                config.protection_state_path.strip()
                or f"data/crypto/perp_protection_{config.base.upper()}.json"
            )
        )
        from quant_rd_tool.crypto_ops_control import make_telemetry_notifier

        self._telemetry = PerpTelemetry(
            TelemetryConfig(
                enabled=config.telemetry_enabled,
                log_dir=config.telemetry_log_dir,
                notifier=make_telemetry_notifier(),
            )
        )

    def _exchange(self, *, authenticated: bool = False):
        if authenticated and not (self.config.api_key and self.config.api_secret):
            msg = "实盘/查余额需要 BINANCE_API_KEY 与 BINANCE_API_SECRET"
            raise ValueError(msg)
        return cxt.create_exchange(
            self.config.exchange_id,
            api_key=self.config.api_key if authenticated else None,
            api_secret=self.config.api_secret if authenticated else None,
            testnet=self.config.testnet,
            market_type="future",
        )

    def fetch_signal(self, *, data_dir: str = "data/crypto", with_ml: bool = True) -> dict[str, Any]:
        report = analyze_crypto(
            self.config.base,
            data_dir=data_dir,
            timeframe=self.config.timeframe,
            limit=self.config.ohlcv_limit,
            refresh=True,
            with_ml=with_ml,
            exchange_id=self.config.exchange_id,
        )
        return {
            "pair": self._perp_pair,
            "spot_pair": self._base_pair,
            "signal": report["combined_signal"],
            "analysis": report["analysis"],
            "period": report["period"],
            "generated_at": report.get("generated_at"),
        }

    def decide_action(self, signal: dict[str, Any]) -> PerpAction:
        action = (signal.get("action") or "hold").lower()
        if action == "buy":
            return "long"
        if action == "sell":
            return "short"
        return "hold"

    def fetch_futures_balance(self) -> dict[str, float]:
        ex = self._exchange(authenticated=True)
        try:
            bal = ex.fetch_balance({"type": "future"})
            free = bal.get("free") or {}
            total = bal.get("total") or {}
            return {
                "USDT_free": float(free.get("USDT") or 0),
                "USDT_total": float(total.get("USDT") or 0),
            }
        finally:
            try:
                ex.close()
            except Exception:
                pass

    def _log_telemetry(
        self,
        result: dict[str, Any],
        *,
        error: BaseException | None = None,
        duration_ms: float | None = None,
        decision: str | None = None,
    ) -> None:
        self._telemetry.log_cycle(
            result=result,
            base=self.config.base,
            error=error,
            duration_ms=duration_ms,
            decision=decision,  # type: ignore[arg-type]
        )

    def run_once(self, *, portfolio_cap_usdt: float | None = None) -> dict[str, Any]:
        started = time.time()
        result: dict[str, Any] = {
            "dry_run": self.config.dry_run,
            "testnet": self.config.testnet,
            "pair": self._perp_pair,
            "signal": {},
            "perp_action": "hold",
            "bar_end": "",
            "target_side": "flat",
            "position_before": None,
            "close_order": None,
            "open_order": None,
            "balance_before": None,
            "circuit_breaker": None,
            "soft_protection": None,
            "message": "",
        }
        try:
            ctx = self.fetch_signal()
            perp_action = self.decide_action(ctx["signal"])
            bar_end = str((ctx.get("period") or {}).get("end") or "")
            state = TradingState.load(self._state_path)
            target_side = _action_to_target(perp_action)

            result.update(
                {
                    "signal": ctx["signal"],
                    "perp_action": perp_action,
                    "bar_end": bar_end,
                    "target_side": target_side,
                }
            )

            if bar_end and not _should_trade_bar(state, bar_end=bar_end):
                result["message"] = "已处理过该周期信号（bar_end 去重），跳过"
                result["skipped_dedup"] = True
                self._log_telemetry(result, duration_ms=(time.time() - started) * 1000, decision="skipped_dedup")
                return result

            from quant_rd_tool.crypto_ops_control import is_kill_switch_active

            if is_kill_switch_active() and not self.config.dry_run:
                result["kill_switch"] = {"active": True}
                result["message"] = "Kill Switch 已启用，跳过实盘下单"
                self._log_telemetry(result, duration_ms=(time.time() - started) * 1000, decision="no_op")
                return result

            prot_state = PerpSymbolState.load(self._protection_state_path)
            prot_state.symbol = self._perp_pair
            cb_blocked, cb_reason = self._evaluate_circuit_breaker(
                prot_state, usdt_total=0.0, persist=False
            )
            result["circuit_breaker"] = {"blocked": cb_blocked, "reason": cb_reason}
            if prot_state.soft_protection_active:
                result["soft_protection"] = {
                    "active": True,
                    "sl_price": prot_state.soft_sl_price,
                    "tp_price": prot_state.soft_tp_price,
                    "side": prot_state.soft_position_side,
                }

            if self.config.dry_run:
                ref_price = self._fetch_public_price()
                sizing = self._resolve_open_sizing(
                    signal=ctx["signal"],
                    free_usdt=0.0,
                    ref_price=ref_price,
                    ex=None,
                )
                result["sizing"] = sizing
                result["open_order"] = self._plan_order(perp_action, sizing=sizing)
                msg = "dry-run：未向交易所下单（永续）"
                if cb_blocked and target_side in ("long", "short"):
                    msg += f"；熔断阻止开仓（{cb_reason}）"
                result["message"] = msg
                if bar_end:
                    state.last_seen_bar_end = bar_end
                    state.last_action = perp_action
                    state.save(self._state_path)
                self._log_telemetry(result, duration_ms=(time.time() - started) * 1000)
                return result

            bal = self.fetch_futures_balance()
            result["balance_before"] = bal
            close_order, open_order, pos, cycle_meta = self._execute_cycle(
                perp_action,
                bal,
                signal=ctx["signal"],
                portfolio_cap_usdt=portfolio_cap_usdt,
            )
            result["sizing"] = cycle_meta.get("sizing")
            result["position_before"] = pos
            result["close_order"] = close_order
            result["open_order"] = open_order
            result["circuit_breaker"] = cycle_meta.get("circuit_breaker")
            result["soft_protection"] = cycle_meta.get("soft_protection")
            msg = "已执行" if (close_order or open_order) else "无下单（hold/同向/余额不足）"
            cb = cycle_meta.get("circuit_breaker") or {}
            if cb.get("blocked") and not open_order:
                msg = f"熔断阻止开仓：{cb.get('reason', '')}"
            sp = cycle_meta.get("soft_protection") or {}
            if sp.get("triggered"):
                msg = f"软保护触发{sp.get('reason', '')}平仓"
            result["message"] = msg
            if bar_end:
                state.last_seen_bar_end = bar_end
                state.last_action = perp_action
                state.save(self._state_path)
            self._log_telemetry(result, duration_ms=(time.time() - started) * 1000)
            return result
        except Exception as e:
            result["message"] = str(e)
            self._log_telemetry(result, error=e, duration_ms=(time.time() - started) * 1000, decision="error")
            raise

    def _plan_order(self, action: PerpAction, *, sizing: dict[str, Any] | None = None) -> dict[str, Any]:
        if action == "hold":
            return {"side": "hold", "status": "skipped"}
        return {
            "type": "market",
            "symbol": self._perp_pair,
            "side": "buy" if action == "long" else "sell",
            "notional_usdt": (sizing or {}).get("notional_usdt"),
            "sizing": sizing,
            "reduceOnly": False,
            "status": "planned",
        }

    def _fetch_atr(self, ex: Any | None = None) -> float | None:
        import pandas as pd

        limit = max(int(self.config.atr_period) + 5, 50)
        try:
            if ex is not None:
                rows = ex.fetch_ohlcv(
                    self._perp_pair,
                    self.config.timeframe,
                    limit=min(limit, self.config.ohlcv_limit),
                )
                if not rows:
                    return None
                df = pd.DataFrame(
                    rows,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )
            else:
                df = cxt.fetch_ohlcv(
                    self.config.base,
                    timeframe=self.config.timeframe,
                    limit=min(limit, self.config.ohlcv_limit),
                    exchange_id=self.config.exchange_id,
                )
            return compute_atr(df, period=int(self.config.atr_period))
        except Exception as e:
            logger.warning("ATR fetch failed for %s: %s", self.config.base, e)
            return None

    def _resolve_open_sizing(
        self,
        *,
        signal: dict[str, Any] | None,
        free_usdt: float,
        ref_price: float,
        ex: Any | None,
        portfolio_cap_usdt: float | None = None,
    ) -> dict[str, Any]:
        atr: float | None = None
        if self.config.sizing_mode in ("atr", "hybrid") or self.config.use_atr_sl_tp:
            atr = self._fetch_atr(ex)
        sizing = resolve_open_notional(
            mode=self.config.sizing_mode,
            free_usdt=float(free_usdt),
            risk_fraction=float(self.config.usdt_risk_fraction),
            confidence=_signal_confidence(signal),
            ref_price=float(ref_price) if ref_price > 0 else 1.0,
            leverage=float(self.config.leverage),
            atr=atr,
            sl_atr=float(self.config.sl_atr),
            min_conf=float(self.config.min_signal_confidence),
            portfolio_cap_usdt=portfolio_cap_usdt,
        )
        return sizing

    def _protection_atr_kwargs(self, atr: float | None) -> dict[str, float]:
        if self.config.use_atr_sl_tp and atr is not None and atr > 0:
            return {
                "atr": float(atr),
                "sl_atr": float(self.config.sl_atr),
                "tp_atr": float(self.config.tp_atr),
            }
        return {}

    def _fetch_position(self, ex) -> tuple[PositionSide, float, list[dict[str, Any]]]:
        rows = ex.fetch_positions([self._perp_pair], {"type": "future"})
        rows = [r for r in (rows or []) if (r.get("symbol") == self._perp_pair)]
        side, amt = _normalize_position_rows(rows, position_epsilon=self.config.position_epsilon)
        return side, amt, rows

    def _fetch_public_price(self) -> float:
        ex = cxt.create_exchange(
            self.config.exchange_id,
            testnet=self.config.testnet,
            market_type="future",
        )
        try:
            ex.load_markets()
            return self._fetch_price(ex)
        except Exception:
            return 0.0
        finally:
            try:
                ex.close()
            except Exception:
                pass

    def _fetch_price(self, ex) -> float:
        t = ex.fetch_ticker(self._perp_pair)
        for k in ("last", "mark", "close"):
            v = t.get(k)
            if v:
                return float(v)
        bid, ask = t.get("bid"), t.get("ask")
        if bid and ask:
            return (float(bid) + float(ask)) / 2
        raise ValueError("无法获取价格")

    def _amount_step(self, ex) -> float:
        m = ex.market(self._perp_pair) or {}
        lim = (m.get("limits") or {}).get("amount") or {}
        if lim.get("min"):
            return float(lim["min"])
        prec = (m.get("precision") or {}).get("amount")
        if isinstance(prec, int) and prec >= 0:
            return 10 ** (-prec)
        return 1e-6

    def _evaluate_circuit_breaker(
        self,
        prot_state: PerpSymbolState,
        *,
        usdt_total: float,
        persist: bool = True,
    ) -> tuple[bool, str]:
        if float(self.config.max_daily_loss_pct) <= 0:
            return False, ""
        if usdt_total <= 0:
            return False, ""

        cb_state = CircuitBreakerState(
            daily_date=prot_state.daily_date,
            daily_start_usdt_total=prot_state.daily_start_usdt_total,
        )
        blocked, updated, reason = should_block_entries(
            state=cb_state,
            usdt_total=usdt_total,
            max_daily_loss_pct=float(self.config.max_daily_loss_pct),
        )
        prot_state.daily_date = updated.daily_date
        prot_state.daily_start_usdt_total = updated.daily_start_usdt_total
        if persist:
            prot_state.save(self._protection_state_path)
        return blocked, reason

    def _handle_soft_protection(
        self,
        ex,
        prot_state: PerpSymbolState,
        *,
        pos_side: PositionSide,
        pos_amt: float,
        last_price: float,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        if pos_side == "flat" or pos_amt <= 0 or not prot_state.soft_protection_active:
            return None
        sl = prot_state.soft_sl_price
        tp = prot_state.soft_tp_price
        side = prot_state.soft_position_side or pos_side
        if sl is None or tp is None or side not in ("long", "short"):
            return {"active": True, "triggered": False, "error": "missing_soft_levels"}

        hit = evaluate_soft_sl_tp(
            position_side=side,  # type: ignore[arg-type]
            last_price=last_price,
            sl_price=float(sl),
            tp_price=float(tp),
        )
        if hit:
            close_side = "sell" if pos_side == "long" else "buy"
            amt = float(ex.amount_to_precision(self._perp_pair, pos_amt))
            order = ex.create_order(
                self._perp_pair,
                "market",
                close_side,
                amt,
                None,
                {**params, "reduceOnly": True},
            )
            reconcile_native_protection(ex, prot_state, position_side="flat", desired=None)
            prot_state.soft_protection_active = False
            prot_state.soft_sl_price = None
            prot_state.soft_tp_price = None
            prot_state.soft_position_side = ""
            prot_state.save(self._protection_state_path)
            return {
                "active": True,
                "triggered": True,
                "reason": hit,
                "close_order_id": order.get("id"),
            }

        if self.config.use_native_protection:
            atr_retry = self._fetch_atr(ex)
            p = build_native_protection_params(
                symbol=self._perp_pair,
                amount=pos_amt,
                position_side=side,  # type: ignore[arg-type]
                ref_price=last_price,
                sl_pct=float(self.config.sl_pct),
                tp_pct=float(self.config.tp_pct),
                trigger_source=self.config.trigger_source,
                client_order_id_prefix=build_client_order_id(
                    symbol=self._perp_pair,
                    bar_end=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
                    target_side=side,
                ),
                **self._protection_atr_kwargs(atr_retry),
            )
            out = try_place_native_sl_tp(ex, p, position_side=side)  # type: ignore[arg-type]
            native_ok = bool(out.get("ok"))
            if out.get("sl"):
                prot_state.sl_order = out["sl"]  # type: ignore[assignment]
            if out.get("tp"):
                prot_state.tp_order = out["tp"]  # type: ignore[assignment]
            policy = decide_protection_policy(
                current_fail_streak=int(prot_state.protection_fail_streak or 0),
                native_ok=native_ok,
                max_failures=int(self.config.max_protection_failures),
            )
            apply_protection_policy_to_state(
                prot_state,
                policy,
                sl_price=p.sl_stop_price,
                tp_price=p.tp_stop_price,
                position_side=side,
            )
            if native_ok:
                reconcile_native_protection(ex, prot_state, position_side=side, desired=p)  # type: ignore[arg-type]
            prot_state.save(self._protection_state_path)
            if bool(policy.get("force_close")):
                close_side = "sell" if pos_side == "long" else "buy"
                order = ex.create_order(
                    self._perp_pair,
                    "market",
                    close_side,
                    float(ex.amount_to_precision(self._perp_pair, pos_amt)),
                    None,
                    {**params, "reduceOnly": True},
                )
                return {
                    "active": False,
                    "triggered": True,
                    "reason": "force_close_protection_fail",
                    "close_order_id": order.get("id"),
                }

        return {"active": True, "triggered": False, "last_price": last_price}

    def _place_protection_after_open(
        self,
        ex,
        prot_state: PerpSymbolState,
        *,
        target_side: Literal["long", "short"],
        amt: float,
        ref_price: float,
        bar_end: str,
        params: dict[str, Any],
        atr: float | None = None,
    ) -> dict[str, Any]:
        if not self.config.use_native_protection:
            return {"skipped": True}

        base_cid = build_client_order_id(
            symbol=self._perp_pair,
            bar_end=bar_end or time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            target_side=target_side,
        )
        p = build_native_protection_params(
            symbol=self._perp_pair,
            amount=amt,
            position_side=target_side,
            ref_price=ref_price,
            sl_pct=float(self.config.sl_pct),
            tp_pct=float(self.config.tp_pct),
            trigger_source=self.config.trigger_source,
            client_order_id_prefix=base_cid,
            **self._protection_atr_kwargs(atr),
        )
        out = try_place_native_sl_tp(ex, p, position_side=target_side)
        native_ok = bool(out.get("ok"))
        if out.get("sl"):
            prot_state.sl_order = out["sl"]  # type: ignore[assignment]
        if out.get("tp"):
            prot_state.tp_order = out["tp"]  # type: ignore[assignment]
        policy = decide_protection_policy(
            current_fail_streak=int(prot_state.protection_fail_streak or 0),
            native_ok=native_ok,
            max_failures=int(self.config.max_protection_failures),
        )
        apply_protection_policy_to_state(
            prot_state,
            policy,
            sl_price=p.sl_stop_price,
            tp_price=p.tp_stop_price,
            position_side=target_side,
        )
        prot_state.save(self._protection_state_path)

        if bool(policy.get("force_close")):
            close_side = "sell" if target_side == "long" else "buy"
            close_order = ex.create_order(
                self._perp_pair,
                "market",
                close_side,
                amt,
                None,
                {**params, "reduceOnly": True},
            )
            return {"force_close": True, "close_order": close_order, "policy": policy}

        if not native_ok:
            return {"native_ok": False, "policy": policy, "error": out.get("error")}

        reconcile_native_protection(ex, prot_state, position_side=target_side, desired=p)
        prot_state.save(self._protection_state_path)
        return {"native_ok": True, "policy": policy}

    def _execute_cycle(
        self,
        action: PerpAction,
        balance: dict[str, float],
        *,
        signal: dict[str, Any] | None = None,
        portfolio_cap_usdt: float | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
        ex = self._exchange(authenticated=True)
        close_order = None
        open_order = None
        cycle_meta: dict[str, Any] = {"circuit_breaker": None, "soft_protection": None}
        try:
            ex.load_markets()
            self._ensure_leverage(ex)

            prot_state = PerpSymbolState.load(self._protection_state_path)
            prot_state.symbol = self._perp_pair
            usdt_total = float(balance.get("USDT_total") or balance.get("USDT_free") or 0)
            cb_blocked, cb_reason = self._evaluate_circuit_breaker(prot_state, usdt_total=usdt_total)
            cycle_meta["circuit_breaker"] = {"blocked": cb_blocked, "reason": cb_reason}

            pos_side, pos_amt, pos_rows = self._fetch_position(ex)
            position_before = {"side": pos_side, "amount": pos_amt, "rows": pos_rows}

            params = {"type": "future"}
            price = self._fetch_price(ex) if pos_side != "flat" else 0.0

            if pos_side != "flat" and pos_amt > 0:
                soft_out = self._handle_soft_protection(
                    ex,
                    prot_state,
                    pos_side=pos_side,
                    pos_amt=pos_amt,
                    last_price=price,
                    params=params,
                )
                cycle_meta["soft_protection"] = soft_out
                if soft_out and soft_out.get("triggered"):
                    pos_side, pos_amt, pos_rows = self._fetch_position(ex)
                    if pos_side == "flat":
                        return (
                            self._wrap_order({"id": soft_out.get("close_order_id")}),
                            None,
                            position_before,
                            cycle_meta,
                        )

            target_side = _action_to_target(action)
            plan = _decide_plan(
                position_side=pos_side,
                target_side=target_side,
                hold_behavior=self.config.hold_behavior,
            )
            plan = apply_circuit_breaker_to_plan(plan=plan, blocked=cb_blocked)

            if plan["close"] and pos_side != "flat" and pos_amt > 0:
                close_side = "sell" if pos_side == "long" else "buy"
                close_order = ex.create_order(
                    self._perp_pair,
                    "market",
                    close_side,
                    float(ex.amount_to_precision(self._perp_pair, pos_amt)),
                    None,
                    {**params, "reduceOnly": True},
                )
                # If we closed the position, cancel stale protection orders best-effort.
                prot_state = PerpSymbolState.load(self._protection_state_path)
                prot_state.symbol = self._perp_pair
                reconcile_native_protection(ex, prot_state, position_side="flat", desired=None)
                prot_state.save(self._protection_state_path)

            if plan["open"] and target_side in ("long", "short"):
                free_usdt = float(balance.get("USDT_free") or 0)
                price = self._fetch_price(ex)
                sizing = self._resolve_open_sizing(
                    signal=signal,
                    free_usdt=free_usdt,
                    ref_price=price,
                    ex=ex,
                    portfolio_cap_usdt=portfolio_cap_usdt,
                )
                cycle_meta["sizing"] = sizing
                notional = float(sizing.get("notional_usdt") or 0)
                if notional < float(self.config.min_notional_usdt):
                    return (
                        self._wrap_order(close_order),
                        None,
                        position_before,
                        cycle_meta,
                    )
                step = self._amount_step(ex)
                amt = _calc_amount_from_notional(notional_usdt=notional, price=price, amount_step=step)
                amt = float(ex.amount_to_precision(self._perp_pair, amt))
                if amt <= 0 or amt * price < float(self.config.min_notional_usdt):
                    return (
                        self._wrap_order(close_order),
                        None,
                        position_before,
                        cycle_meta,
                    )
                open_side = "buy" if target_side == "long" else "sell"
                open_order = ex.create_order(self._perp_pair, "market", open_side, amt, None, params)

                prot_out = self._place_protection_after_open(
                    ex,
                    prot_state,
                    target_side=target_side,
                    amt=amt,
                    ref_price=price,
                    bar_end="",
                    params=params,
                    atr=sizing.get("atr"),
                )
                cycle_meta["protection"] = prot_out
                if prot_out.get("force_close"):
                    close_order = prot_out.get("close_order")
                    cycle_meta["soft_protection"] = {
                        "active": False,
                        "triggered": True,
                        "reason": "force_close_protection_fail",
                    }

            return self._wrap_order(close_order), self._wrap_order(open_order), position_before, cycle_meta
        finally:
            try:
                ex.close()
            except Exception:
                pass

    def run_forever(self) -> None:
        logger.info("Perp bot started: %s interval=%sm", self._perp_pair, self.config.interval_minutes)
        while True:
            started = time.time()
            try:
                self.run_once()
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.exception("Perp bot cycle failed")
            elapsed = time.time() - started
            sleep_s = max(self.config.interval_minutes * 60 - elapsed, 5)
            time.sleep(sleep_s)

    @staticmethod
    def _wrap_order(o: dict[str, Any] | None) -> dict[str, Any] | None:
        if not o:
            return None
        return {
            "id": o.get("id"),
            "side": o.get("side"),
            "symbol": o.get("symbol"),
            "amount": o.get("amount"),
            "cost": o.get("cost"),
            "status": o.get("status"),
            "raw": {k: o.get(k) for k in ("id", "side", "price", "average", "filled")},
        }

    def _ensure_leverage(self, ex) -> None:
        try:
            ex.set_leverage(int(self.config.leverage), self._perp_pair, {"type": "future"})
        except Exception as e:
            logger.warning("set_leverage failed: %s", e)
