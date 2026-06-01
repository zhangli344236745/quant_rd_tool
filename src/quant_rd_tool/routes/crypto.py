from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quant_rd_tool.binance_bot import BinanceBot, BotConfig
from quant_rd_tool.binance_perp_bot import BinancePerpBot, PerpBotConfig
from quant_rd_tool.config import settings
from quant_rd_tool.crypto_analysis import analyze_crypto

router = APIRouter()


@router.get("/connectivity")
def crypto_connectivity(
    exchange: str = "binance",
    symbol: str = "BTC",
    timeframe: str = "5m",
    test_ohlcv: bool = True,
) -> dict[str, Any]:
    from quant_rd_tool.ccxt_connectivity import check_connectivity

    report = check_connectivity(
        exchange,  # type: ignore[arg-type]
        test_ohlcv=test_ohlcv,
        symbol=symbol,
        timeframe=timeframe,
    )
    if not report.get("ok"):
        raise HTTPException(status_code=503, detail=report)
    return report


class CryptoAnalyzeRequest(BaseModel):
    symbol: str = Field("BTC", examples=["BTC", "ETH"])
    timeframe: str = "1d"
    limit: int = 500
    data_dir: str = "data/crypto"
    with_ml: bool = True
    ml_algorithm: str = Field("both", description="xgb | lgb | both")
    with_options_vol: bool = Field(
        True,
        description="并入 Binance 期权 ATM IV 与现货/ML 联合研判",
    )


class CryptoMlRequest(BaseModel):
    symbol: str = "BTC"
    data_dir: str = "data/crypto"
    algorithm: str = "both"


class CryptoBotRequest(BaseModel):
    symbol: str = "BTC"
    quote: str = "USDT"
    quote_amount: float = 50.0
    timeframe: str = "1d"
    dry_run: bool = True
    testnet: bool = False
    signal_only: bool = False


class CryptoPerpPortfolioRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTC", "ETH"])
    quote: str = "USDT"
    timeframe: str = "5m"
    ohlcv_limit: int = 800
    leverage: int = 3
    usdt_risk_fraction: float = 0.20
    min_notional_usdt: float = 10.0
    total_notional_usdt: float = 0.0
    max_per_symbol_notional_usdt: float = 0.0
    max_concurrent_positions: int = 0
    dry_run: bool = True
    testnet: bool = False
    signal_only: bool = False


class CryptoPerpBotRequest(BaseModel):
    base: str = "BTC"
    quote: str = "USDT"
    timeframe: str = "5m"
    ohlcv_limit: int = 800
    leverage: int = 3
    usdt_risk_fraction: float = 0.20
    min_notional_usdt: float = 10.0
    max_daily_loss_pct: float = 0.03
    sl_pct: float = 0.01
    tp_pct: float = 0.015
    sizing_mode: str = "hybrid"
    atr_period: int = 14
    sl_atr: float = 1.5
    tp_atr: float = 2.5
    use_atr_sl_tp: bool = True
    max_protection_failures: int = 3
    telemetry_enabled: bool = True
    telemetry_log_dir: str = "data/crypto/perp_logs"
    dry_run: bool = True
    testnet: bool = False
    signal_only: bool = False
    ccxt_symbol: str = ""


class CryptoScheduleRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTC", "ETH"])
    timeframe: str = "5m"
    interval_minutes: int = 30
    backfill_days: int = 90
    data_dir: str = "data/crypto"
    with_ml: bool = True
    ml_algorithm: str = "both"
    once: bool = True


class CryptoScheduleCreateRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTC", "ETH"])
    name: str = ""
    id: str = ""
    timeframe: str = "5m"
    interval_minutes: int = 30
    backfill_days: int = 90
    data_dir: str = "data/crypto"
    with_ml: bool = True
    ml_algorithm: str = "both"
    auto_start: bool = False


@router.post("/analyze")
def crypto_analyze(req: CryptoAnalyzeRequest) -> dict[str, Any]:
    try:
        return analyze_crypto(
            req.symbol,
            data_dir=req.data_dir,
            timeframe=req.timeframe,
            limit=req.limit,
            with_ml=req.with_ml,
            ml_algorithm=req.ml_algorithm,  # type: ignore[arg-type]
            with_options_vol=req.with_options_vol,
        )
    except (ConnectionError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/ml")
def crypto_ml(req: CryptoMlRequest) -> dict[str, Any]:
    from pathlib import Path

    import pandas as pd

    from quant_rd_tool import ccxt_data as cxt
    from quant_rd_tool.crypto_ml import run_crypto_ml_analysis

    root = Path(req.data_dir) / cxt.to_qlib_code(req.symbol)
    csv_file = root / "ohlcv.csv"
    if not csv_file.exists():
        raise HTTPException(status_code=400, detail="请先调用 /crypto/analyze 拉取并落盘数据")
    df = pd.read_csv(csv_file)
    df["date"] = pd.to_datetime(df["date"])
    try:
        return run_crypto_ml_analysis(
            str((root / "qlib").resolve()),
            cxt.to_qlib_code(req.symbol),
            start_date=str(df["date"].min().date()),
            end_date=str(df["date"].max().date()),
            num_bars=len(df),
            algorithm=req.algorithm,  # type: ignore[arg-type]
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/bot/run")
def crypto_bot_run(req: CryptoBotRequest) -> dict[str, Any]:
    if not req.dry_run and not (settings.binance_api_key and settings.binance_api_secret):
        raise HTTPException(status_code=400, detail="实盘需配置 BINANCE_API_KEY / BINANCE_API_SECRET")
    cfg = BotConfig(
        symbol=req.symbol,
        quote=req.quote,
        quote_amount=req.quote_amount,
        timeframe=req.timeframe,
        dry_run=req.dry_run,
        testnet=req.testnet or settings.binance_testnet,
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
    )
    bot = BinanceBot(cfg)
    try:
        if req.signal_only:
            return bot.fetch_signal()
        return bot.run_once()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/perp-bot/run")
def crypto_perp_bot_run(req: CryptoPerpBotRequest) -> dict[str, Any]:
    if not req.dry_run and not (settings.binance_api_key and settings.binance_api_secret):
        raise HTTPException(status_code=400, detail="实盘需配置 BINANCE_API_KEY / BINANCE_API_SECRET")
    cfg = PerpBotConfig(
        base=req.base,
        quote=req.quote,
        timeframe=req.timeframe,
        ohlcv_limit=req.ohlcv_limit,
        leverage=req.leverage,
        usdt_risk_fraction=req.usdt_risk_fraction,
        min_notional_usdt=req.min_notional_usdt,
        max_daily_loss_pct=req.max_daily_loss_pct,
        sl_pct=req.sl_pct,
        tp_pct=req.tp_pct,
        sizing_mode=req.sizing_mode,  # type: ignore[arg-type]
        atr_period=req.atr_period,
        sl_atr=req.sl_atr,
        tp_atr=req.tp_atr,
        use_atr_sl_tp=req.use_atr_sl_tp,
        max_protection_failures=req.max_protection_failures,
        telemetry_enabled=req.telemetry_enabled,
        telemetry_log_dir=req.telemetry_log_dir,
        dry_run=req.dry_run,
        testnet=req.testnet or settings.binance_testnet,
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        ccxt_symbol=req.ccxt_symbol,
    )
    bot = BinancePerpBot(cfg)
    try:
        if req.signal_only:
            return bot.fetch_signal()
        return bot.run_once()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/perp-portfolio/run")
def crypto_perp_portfolio_run(req: CryptoPerpPortfolioRequest) -> dict[str, Any]:
    if not req.dry_run and not (settings.binance_api_key and settings.binance_api_secret):
        raise HTTPException(status_code=400, detail="实盘需配置 BINANCE_API_KEY / BINANCE_API_SECRET")
    from quant_rd_tool.binance_perp_bot import BinancePerpBot, PerpBotConfig
    from quant_rd_tool.perp_portfolio import PortfolioRunConfig, run_portfolio_once

    symbols = [s.strip().upper() for s in req.symbols if s and s.strip()]
    bots: dict[str, BinancePerpBot] = {}
    for sym in symbols:
        cfg = PerpBotConfig(
            base=sym,
            quote=req.quote,
            timeframe=req.timeframe,
            ohlcv_limit=req.ohlcv_limit,
            leverage=req.leverage,
            usdt_risk_fraction=req.usdt_risk_fraction,
            min_notional_usdt=req.min_notional_usdt,
            dry_run=req.dry_run,
            testnet=req.testnet or settings.binance_testnet,
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
        )
        bots[sym] = BinancePerpBot(cfg)

    pf_cfg = PortfolioRunConfig(
        symbols=symbols,
        total_notional_usdt=req.total_notional_usdt,
        max_per_symbol_notional_usdt=req.max_per_symbol_notional_usdt,
        max_concurrent_positions=req.max_concurrent_positions,
    )
    try:
        return run_portfolio_once(bots, config=pf_cfg, signal_only=req.signal_only)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/schedule/run")
def crypto_schedule_run(req: CryptoScheduleRequest) -> dict[str, Any]:
    from quant_rd_tool.crypto_scheduler import run_scheduled_cycle

    try:
        results = run_scheduled_cycle(
            req.symbols,
            data_dir=req.data_dir,
            timeframe=req.timeframe,
            backfill_days=req.backfill_days,
            with_ml=req.with_ml,
            ml_algorithm=req.ml_algorithm,  # type: ignore[arg-type]
        )
        return {"once": req.once, "results": results}
    except (ConnectionError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/schedules")
def crypto_schedules_list(data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    jobs = mgr.list_jobs()
    return {"count": len(jobs), "jobs": jobs}


class ScheduleAlertRulesRequest(BaseModel):
    enabled: bool | None = None
    on_cycle_error: bool | None = None
    on_worker_crash: bool | None = None
    consecutive_failures: int | None = Field(None, ge=0, le=20)
    stale_minutes: int | None = Field(None, ge=0, le=1440)
    cooldown_minutes: int | None = Field(None, ge=1, le=1440)
    custom_rules: list[dict[str, Any]] | None = None


@router.get("/schedules/alerts/rules")
def schedule_alerts_rules_get() -> dict[str, Any]:
    from quant_rd_tool.schedule_alerts import get_alert_rules

    return get_alert_rules()


@router.get("/schedules/alerts/rules/format")
def schedule_alerts_rules_format() -> dict[str, Any]:
    from quant_rd_tool import schedule_alert_conditions as sac

    return {
        "doc": sac.__doc__,
        "example_rules": [
            {
                "id": "btc-bull",
                "name": "BTC 转多",
                "enabled": True,
                "job_ids": [],
                "symbol_scope": "any_symbol",
                "logic": "and",
                "conditions": [
                    {"field": "symbol", "op": "eq", "value": "BTC"},
                    {"field": "stance", "op": "eq", "value": "看涨"},
                ],
                "message": "[{job_id}] {symbol} 立场 {stance}，动作 {action}",
            },
            {
                "id": "eth-sell-pressure",
                "name": "ETH 偏空",
                "enabled": True,
                "job_ids": ["eth-5m"],
                "symbol_scope": "any_symbol",
                "logic": "or",
                "conditions": [
                    {"field": "symbol", "op": "eq", "value": "ETH"},
                    {"field": "action", "op": "in", "value": ["sell", "short"]},
                ],
                "message": "{symbol} 出现卖出方向信号",
            },
        ],
    }


@router.post("/schedules/alerts/rules")
def schedule_alerts_rules_save(req: ScheduleAlertRulesRequest) -> dict[str, Any]:
    from quant_rd_tool.schedule_alerts import save_alert_rules

    try:
        return save_alert_rules(
            enabled=req.enabled,
            on_cycle_error=req.on_cycle_error,
            on_worker_crash=req.on_worker_crash,
            consecutive_failures=req.consecutive_failures,
            stale_minutes=req.stale_minutes,
            cooldown_minutes=req.cooldown_minutes,
            custom_rules=req.custom_rules,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/schedules/alerts/log")
def schedule_alerts_log(limit: int = 50) -> dict[str, Any]:
    from quant_rd_tool.schedule_alerts import tail_alert_log

    items = tail_alert_log(limit=min(limit, 200))
    return {"count": len(items), "items": items}


@router.post("/schedules/alerts/check-stale")
def schedule_alerts_check_stale(data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    fired = mgr.check_stale_alerts()
    return {"fired": fired, "count": len(fired)}


@router.get("/schedules/{job_id}")
def crypto_schedules_get(job_id: str, data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    job = mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")
    return job


@router.post("/schedules")
def crypto_schedules_create(req: CryptoScheduleCreateRequest) -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import ScheduleJobConfig, get_scheduler_manager

    mgr = get_scheduler_manager(req.data_dir)
    cfg = ScheduleJobConfig(
        symbols=req.symbols,
        name=req.name,
        id=req.id,
        timeframe=req.timeframe,
        interval_minutes=req.interval_minutes,
        backfill_days=req.backfill_days,
        data_dir=req.data_dir,
        with_ml=req.with_ml,
        ml_algorithm=req.ml_algorithm,
    )
    try:
        return mgr.add_job(cfg, auto_start=req.auto_start)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/schedules/{job_id}/start")
def crypto_schedules_start(job_id: str, data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    try:
        return mgr.start_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/schedules/{job_id}/stop")
def crypto_schedules_stop(job_id: str, data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    try:
        return mgr.stop_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/schedules/{job_id}/run-once")
def crypto_schedules_run_once(job_id: str, data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    try:
        return mgr.run_once(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (ConnectionError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.delete("/schedules/{job_id}")
def crypto_schedules_delete(job_id: str, data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    try:
        return mgr.remove_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class CryptoOpsControlRequest(BaseModel):
    kill_switch: bool | None = None
    webhook_url: str | None = None
    webhook_on_error: bool | None = None
    webhook_on_circuit_breaker: bool | None = None


@router.get("/ops/control")
def crypto_ops_control_get() -> dict[str, Any]:
    from quant_rd_tool.crypto_ops_control import get_crypto_ops

    return get_crypto_ops()


@router.post("/ops/control")
def crypto_ops_control_save(req: CryptoOpsControlRequest) -> dict[str, Any]:
    from quant_rd_tool.crypto_ops_control import save_crypto_ops

    return save_crypto_ops(
        kill_switch=req.kill_switch,
        webhook_url=req.webhook_url,
        webhook_on_error=req.webhook_on_error,
        webhook_on_circuit_breaker=req.webhook_on_circuit_breaker,
    )


@router.post("/ops/control/test-webhook")
def crypto_ops_test_webhook() -> dict[str, str]:
    from quant_rd_tool.crypto_ops_control import get_crypto_ops, post_webhook

    ops = get_crypto_ops()
    url = (ops.get("webhook_url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="webhook_url not configured")
    post_webhook(
        url,
        {
            "kind": "test",
            "decision": "no_op",
            "message": "quant-rd-tool webhook test",
        },
    )
    return {"status": "sent"}


@router.get("/ops/summary")
def crypto_ops_summary(
    data_dir: str = "data/crypto",
    log_dir: str = "data/crypto/perp_logs",
    telemetry_limit: int = 80,
) -> dict[str, Any]:
    """Schedules + perp state files + recent telemetry for ops dashboard."""
    from quant_rd_tool.crypto_ops import build_ops_summary

    return build_ops_summary(
        data_dir=data_dir,
        log_dir=log_dir,
        telemetry_limit=min(telemetry_limit, 500),
    )


@router.get("/perp/telemetry")
def crypto_perp_telemetry(
    log_dir: str = "data/crypto/perp_logs",
    day: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    from datetime import datetime

    from quant_rd_tool.crypto_ops import list_telemetry_days, summarize_telemetry, tail_jsonl

    d = None
    if day:
        try:
            d = datetime.strptime(day, "%Y%m%d").date()
        except ValueError as e:
            raise HTTPException(status_code=400, detail="day must be YYYYMMDD") from e
    events = tail_jsonl(log_dir, day=d, limit=min(limit, 500))
    return {
        "log_dir": log_dir,
        "day": day or (d.strftime("%Y%m%d") if d else None),
        "available_days": list_telemetry_days(log_dir),
        "summary": summarize_telemetry(events),
        "items": events,
    }


@router.get("/perp/states")
def crypto_perp_states(data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.crypto_ops import list_perp_states

    items = list_perp_states(data_dir)
    return {"data_dir": data_dir, "count": len(items), "items": items}


class OptionsVolConfigBody(BaseModel):
    symbols: list[str] | None = None
    lookback_days: int | None = Field(None, ge=7, le=365)
    iv_percentile_threshold: float | None = Field(None, ge=50, le=99)
    iv_change_24h_threshold: float | None = Field(None, ge=1, le=100)


@router.get("/options/volatility-scan")
def crypto_options_volatility_scan(
    symbols: str | None = None,
    lookback_days: int | None = None,
    data_dir: str = "data/crypto",
    persist: bool = True,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_advisor import build_scan_advice
    from quant_rd_tool.crypto_options_vol_scan import run_volatility_scan

    sym_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    try:
        scan = run_volatility_scan(
            symbols=sym_list,
            lookback_days=lookback_days,
            data_dir=data_dir,
            persist_snapshot=persist,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    advice = build_scan_advice(scan)
    return {**scan, "advice_pack": advice}


@router.get("/options/volatility-scan/config")
def crypto_options_volatility_config_get(data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.crypto_options_vol_scan import get_scan_config

    return get_scan_config(data_dir)


@router.post("/options/volatility-scan/config")
def crypto_options_volatility_config_save(
    body: OptionsVolConfigBody,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_vol_scan import save_scan_config

    return save_scan_config(
        data_dir=data_dir,
        symbols=body.symbols,
        lookback_days=body.lookback_days,
        iv_percentile_threshold=body.iv_percentile_threshold,
        iv_change_24h_threshold=body.iv_change_24h_threshold,
    )


@router.get("/options/volatility-scan/history")
def crypto_options_volatility_history(
    symbol: str,
    data_dir: str = "data/crypto",
    limit: int = 120,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_data import load_history

    items = load_history(symbol, data_dir=data_dir, limit=min(limit, 500))
    return {"symbol": symbol.upper(), "count": len(items), "items": items}


@router.get("/options/strike-probability")
def crypto_options_strike_probability(
    base: str,
    n: int | None = None,
    expiry: str | None = None,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_strike_probs import build_strike_probability_report

    try:
        return build_strike_probability_report(
            base,
            n=n,
            data_dir=data_dir,
            expiry_iso=expiry,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
