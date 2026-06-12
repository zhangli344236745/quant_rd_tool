import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
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
    use_cache: bool = True


class CryptoBotRequest(BaseModel):
    symbol: str = "BTC"
    quote: str = "USDT"
    quote_amount: float = 50.0
    timeframe: str = "1d"
    dry_run: bool = True
    testnet: bool = False
    signal_only: bool = False

    # Risk / sizing
    sizing_mode: str = "hybrid"  # fixed | atr | hybrid
    risk_fraction: float = 0.5
    min_signal_confidence: float = 0.0
    use_atr_sl_tp: bool = True
    sl_pct: float = 0.03
    tp_pct: float = 0.06
    sl_atr: float = 1.5
    tp_atr: float = 2.5

    # Signal enhancement
    use_enhanced_signal: bool = True
    require_htf_confirm: bool = True
    require_volume_confirm: bool = False
    min_atr_pct: float = 0.0
    max_atr_pct: float = 0.0
    volume_min_ratio: float = 1.0

    # Paper trading
    paper_mode: bool = False
    paper_initial_cash: float = 10_000.0
    fee_pct: float = 0.001
    slippage_pct: float = 0.0005


def _build_bot_config(req: CryptoBotRequest) -> BotConfig:
    return BotConfig(
        symbol=req.symbol,
        quote=req.quote,
        quote_amount=req.quote_amount,
        timeframe=req.timeframe,
        dry_run=req.dry_run,
        testnet=req.testnet or settings.binance_testnet,
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        sizing_mode=req.sizing_mode,  # type: ignore[arg-type]
        risk_fraction=req.risk_fraction,
        min_signal_confidence=req.min_signal_confidence,
        use_atr_sl_tp=req.use_atr_sl_tp,
        sl_pct=req.sl_pct,
        tp_pct=req.tp_pct,
        sl_atr=req.sl_atr,
        tp_atr=req.tp_atr,
        use_enhanced_signal=req.use_enhanced_signal,
        require_htf_confirm=req.require_htf_confirm,
        require_volume_confirm=req.require_volume_confirm,
        min_atr_pct=req.min_atr_pct,
        max_atr_pct=req.max_atr_pct,
        volume_min_ratio=req.volume_min_ratio,
        paper_mode=req.paper_mode,
        paper_initial_cash=req.paper_initial_cash,
        fee_pct=req.fee_pct,
        slippage_pct=req.slippage_pct,
    )


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
    job_type: str = Field("analysis", description="analysis | news")


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
            use_cache=req.use_cache,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/bot/run")
def crypto_bot_run(req: CryptoBotRequest) -> dict[str, Any]:
    if not req.dry_run and not req.paper_mode and not (
        settings.binance_api_key and settings.binance_api_secret
    ):
        raise HTTPException(
            status_code=400, detail="实盘需配置 BINANCE_API_KEY / BINANCE_API_SECRET"
        )
    bot = BinanceBot(_build_bot_config(req))
    try:
        if req.signal_only:
            return bot.fetch_signal()
        return bot.run_once()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/bot/paper/performance")
def crypto_bot_paper_performance(
    symbol: str = "BTC",
    quote: str = "USDT",
    paper_initial_cash: float = 10_000.0,
) -> dict[str, Any]:
    bot = BinanceBot(
        BotConfig(
            symbol=symbol, quote=quote, paper_mode=True, paper_initial_cash=paper_initial_cash
        )
    )
    return bot.paper_performance()


@router.post("/bot/paper/reset")
def crypto_bot_paper_reset(req: CryptoBotRequest) -> dict[str, Any]:
    bot = BinanceBot(_build_bot_config(req))
    return bot.reset_paper()


def _build_perp_bot_config(req: CryptoPerpBotRequest) -> PerpBotConfig:
    return PerpBotConfig(
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
        interval_minutes=10,
    )


class BotScheduleRequest(BaseModel):
    bot_id: str = ""
    kind: str = "spot"  # spot | perp
    interval_minutes: int = 60
    spot: CryptoBotRequest | None = None
    perp: CryptoPerpBotRequest | None = None


@router.get("/bot/scheduler/status")
def crypto_bot_scheduler_status() -> dict[str, Any]:
    from quant_rd_tool.crypto_bot_scheduler import get_scheduler

    return {"bots": get_scheduler().status()}


@router.post("/bot/scheduler/register")
def crypto_bot_scheduler_register(req: BotScheduleRequest) -> dict[str, Any]:
    from quant_rd_tool.crypto_bot_scheduler import get_scheduler

    kind = (req.kind or "spot").strip().lower()
    if kind not in ("spot", "perp"):
        raise HTTPException(status_code=400, detail="kind 须为 spot 或 perp")

    sched = get_scheduler()
    try:
        if kind == "spot":
            if req.spot is None:
                raise HTTPException(status_code=400, detail="spot 调度需提供 spot 配置")
            spot_req = req.spot
            if not spot_req.dry_run and not spot_req.paper_mode and not (
                settings.binance_api_key and settings.binance_api_secret
            ):
                raise HTTPException(status_code=400, detail="实盘调度需配置 API Key")
            bot_id = req.bot_id.strip() or f"spot-{spot_req.symbol.upper()}-{spot_req.timeframe}"
            cfg = _build_bot_config(spot_req)
            managed = sched.register(
                bot_id=bot_id,
                kind="spot",
                config=cfg.__dict__,
                interval_minutes=req.interval_minutes,
            )
        else:
            if req.perp is None:
                raise HTTPException(status_code=400, detail="perp 调度需提供 perp 配置")
            perp_req = req.perp
            if not perp_req.dry_run and not (
                settings.binance_api_key and settings.binance_api_secret
            ):
                raise HTTPException(status_code=400, detail="永续实盘调度需配置 API Key")
            bot_id = req.bot_id.strip() or f"perp-{perp_req.base.upper()}-{perp_req.timeframe}"
            cfg = _build_perp_bot_config(perp_req)
            managed = sched.register(
                bot_id=bot_id,
                kind="perp",
                config=cfg.__dict__,
                interval_minutes=req.interval_minutes,
            )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return managed.public()


@router.post("/bot/scheduler/start")
def crypto_bot_scheduler_start(bot_id: str = Query(...)) -> dict[str, Any]:
    from quant_rd_tool.crypto_bot_scheduler import get_scheduler

    try:
        return get_scheduler().start(bot_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/bot/scheduler/stop")
def crypto_bot_scheduler_stop(bot_id: str = Query(...)) -> dict[str, Any]:
    from quant_rd_tool.crypto_bot_scheduler import get_scheduler

    try:
        return get_scheduler().stop(bot_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/bot/scheduler/remove")
def crypto_bot_scheduler_remove(bot_id: str = Query(...)) -> dict[str, Any]:
    from quant_rd_tool.crypto_bot_scheduler import get_scheduler

    try:
        return get_scheduler().remove(bot_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/perp-bot/run")
def crypto_perp_bot_run(req: CryptoPerpBotRequest) -> dict[str, Any]:
    if not req.dry_run and not (settings.binance_api_key and settings.binance_api_secret):
        raise HTTPException(status_code=400, detail="实盘需配置 BINANCE_API_KEY / BINANCE_API_SECRET")
    bot = BinancePerpBot(_build_perp_bot_config(req))
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
    var: dict[str, Any] | None = None
    bark: dict[str, Any] | None = None
    webhook_on_alert: bool | None = None
    on_cycle_complete: bool | None = None
    crypto_news: dict[str, Any] | None = None


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
            {
                "id": "btc-iv-hot",
                "name": "BTC 期权 IV 偏高",
                "enabled": True,
                "conditions": [
                    {"field": "symbol", "op": "eq", "value": "BTC"},
                    {"field": "iv_alert_level", "op": "in", "value": ["hot", "elevated"]},
                ],
                "message": "[{job_id}] {symbol} IV {iv_alert_level} 分位{iv_percentile}%",
            },
            {
                "id": "btc-var-high",
                "name": "BTC VaR 超 5%",
                "enabled": True,
                "conditions": [
                    {"field": "symbol", "op": "eq", "value": "BTC"},
                    {"field": "var_pct", "op": "gte", "value": 0.05},
                ],
                "message": "[{job_id}] {symbol} VaR {var_pct} (≈{var_usdt} USDT)",
            },
        ],
        "example_var_config": {
            "enabled": True,
            "on_symbol_var_breach": True,
            "on_portfolio_var_breach": False,
            "max_var_pct": 0.05,
            "max_portfolio_var_pct_of_equity": 0.10,
            "confidence": 0.99,
            "notional_usdt": 10000,
            "lookback_bars": 252,
            "horizon_days": 1,
            "mc_n_sims": 3000,
        },
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
            var=req.var,
            bark=req.bark,
            webhook_on_alert=req.webhook_on_alert,
            on_cycle_complete=req.on_cycle_complete,
            crypto_news=req.crypto_news,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/schedules/alerts/test-bark")
async def schedule_alerts_test_bark(
    request: Request,
    device_key: str | None = Query(None, description="Bark Device Key（与 JSON body 二选一）"),
    server: str | None = Query(None, description="Bark API 根地址"),
) -> dict[str, Any]:
    """Test Bark push. Body or query: ``device_key`` required."""
    from quant_rd_tool.bark_push import DEFAULT_BARK_SERVER
    from quant_rd_tool.schedule_alerts import (
        _bark_from_env,
        _coerce_bool,
        _normalize_bark_config,
        save_alert_rules,
        send_test_bark,
    )

    raw: dict[str, Any] = {}
    body_bytes = await request.body()
    if body_bytes:
        try:
            parsed = json.loads(body_bytes)
            if isinstance(parsed, dict):
                raw = parsed
        except json.JSONDecodeError:
            pass

    bark_in: dict[str, Any] | None = None
    if isinstance(raw.get("bark"), dict):
        bark_in = dict(raw["bark"])
    elif str(raw.get("device_key") or "").strip():
        bark_in = dict(raw)

    q_key = str(device_key or "").strip()
    if not bark_in and q_key:
        bark_in = {
            "device_key": q_key,
            "server": str(server or DEFAULT_BARK_SERVER).strip() or DEFAULT_BARK_SERVER,
            "enabled": True,
        }
    elif isinstance(bark_in, dict) and q_key and not str(bark_in.get("device_key") or "").strip():
        bark_in["device_key"] = q_key
    if isinstance(bark_in, dict) and server and not str(bark_in.get("server") or "").strip():
        bark_in["server"] = str(server).strip()

    env_key = _bark_from_env()["device_key"]
    merged = _normalize_bark_config(bark_in if isinstance(bark_in, dict) else {})
    if not merged["device_key"] and not env_key:
        raise HTTPException(
            status_code=400,
            detail="请在 .env 设置 BARK_DEVICE_KEY，或在页面填写 Device Key",
        )

    try:
        result = send_test_bark(bark_in if isinstance(bark_in, dict) else {})
        to_save: dict[str, Any] = dict(bark_in) if isinstance(bark_in, dict) else {}
        if not _coerce_bool(to_save.get("enabled"), default=False):
            to_save["enabled"] = True
        try:
            save_alert_rules(bark=to_save)
        except ValueError as save_err:
            return {"status": "ok", "result": result, "save_warning": str(save_err)}
        return {"status": "ok", "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


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
        job_type=req.job_type if req.job_type in ("analysis", "news") else "analysis",  # type: ignore[arg-type]
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

@router.get("/perp/orders/open")
def crypto_perp_open_orders(
    base: str,
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    from quant_rd_tool.perp_order_manager import list_open_orders

    try:
        return list_open_orders(base=base, quote=quote, ccxt_symbol=ccxt_symbol, testnet=testnet)
    except ValueError as e:
        # Allow UI to open even when API keys are missing.
        msg = str(e)
        if "BINANCE_API_KEY" in msg or "BINANCE_API_SECRET" in msg:
            sym = (ccxt_symbol or "").strip() or f"{base.strip().upper()}/{quote.strip().upper()}:{quote.strip().upper()}"
            return {"enabled": False, "symbol": sym, "count": 0, "items": [], "error": msg}
        raise HTTPException(status_code=400, detail=msg) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/perp/orders/cancel")
def crypto_perp_cancel_order(
    base: str,
    order_id: str,
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    from quant_rd_tool.perp_order_manager import cancel_order

    try:
        return cancel_order(
            base=base,
            order_id=order_id,
            quote=quote,
            ccxt_symbol=ccxt_symbol,
            testnet=testnet,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/perp/orders/cancel-all")
def crypto_perp_cancel_all(
    base: str,
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    from quant_rd_tool.perp_order_manager import cancel_all_orders

    try:
        return cancel_all_orders(base=base, quote=quote, ccxt_symbol=ccxt_symbol, testnet=testnet)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/perp/position")
def crypto_perp_position(
    base: str,
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    from quant_rd_tool.perp_order_manager import get_position

    try:
        return get_position(base=base, quote=quote, ccxt_symbol=ccxt_symbol, testnet=testnet)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/perp/account/balances")
def crypto_perp_account_balances(testnet: bool = False) -> dict[str, Any]:
    from quant_rd_tool.perp_account_analytics import fetch_future_balances

    try:
        return fetch_future_balances(testnet=testnet)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/perp/account/trades")
def crypto_perp_account_trades(
    base: str = "ETH",
    quote: str = "USDT",
    limit: int = 50,
    testnet: bool = False,
) -> dict[str, Any]:
    from quant_rd_tool.perp_account_analytics import fetch_recent_trades

    try:
        return fetch_recent_trades(base=base, quote=quote, limit=min(limit, 200), testnet=testnet)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/perp/account/daily-pnl")
def crypto_perp_account_daily_pnl(days: int = 7, testnet: bool = False) -> dict[str, Any]:
    from quant_rd_tool.perp_account_analytics import fetch_daily_pnl

    try:
        return fetch_daily_pnl(days=days, testnet=testnet)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/perp/position/close")
def crypto_perp_close_position(
    base: str,
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    from quant_rd_tool.perp_order_manager import close_position_market

    try:
        return close_position_market(base=base, quote=quote, ccxt_symbol=ccxt_symbol, testnet=testnet)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/perp/protection/reconcile")
def crypto_perp_reconcile_protection(
    base: str,
    data_dir: str = "data/crypto",
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    from quant_rd_tool.perp_order_manager import reconcile_protection_from_state

    try:
        return reconcile_protection_from_state(
            base=base,
            data_dir=data_dir,
            quote=quote,
            ccxt_symbol=ccxt_symbol,
            testnet=testnet,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/var/symbol")
def crypto_var_symbol(
    symbol: str = "BTC",
    notional_usdt: float = 0.0,
    timeframe: str = "1d",
    lookback_bars: int = 252,
    horizon_days: int = 1,
    confidence: str = "0.95,0.99",
    mc_n_sims: int = 10_000,
    mc_seed: int = 42,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_var import build_symbol_var_report, parse_confidence_levels

    levels = parse_confidence_levels(confidence)
    try:
        return build_symbol_var_report(
            symbol=symbol,
            notional_usdt=notional_usdt,
            timeframe=timeframe,
            lookback_bars=min(lookback_bars, 2000),
            horizon_days=horizon_days,
            confidence_levels=levels,
            mc_n_sims=mc_n_sims,
            mc_seed=mc_seed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/var/portfolio")
def crypto_var_portfolio(
    testnet: bool = False,
    timeframe: str = "1d",
    lookback_bars: int = 252,
    horizon_days: int = 1,
    confidence: str = "0.95,0.99",
    mc_n_sims: int = 10_000,
    mc_seed: int = 42,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_var import build_portfolio_var_report, parse_confidence_levels

    levels = parse_confidence_levels(confidence)
    try:
        return build_portfolio_var_report(
            testnet=testnet,
            timeframe=timeframe,
            lookback_bars=min(lookback_bars, 2000),
            horizon_days=horizon_days,
            confidence_levels=levels,
            mc_n_sims=mc_n_sims,
            mc_seed=mc_seed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/var/symbol/history")
def crypto_var_symbol_history(
    symbol: str = "BTC",
    window: int = 60,
    confidence: float = 0.99,
    timeframe: str = "1d",
    lookback_bars: int = 252,
    horizon_days: int = 1,
    notional_usdt: float = 0.0,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_var import build_symbol_var_history

    try:
        return build_symbol_var_history(
            symbol=symbol,
            window=min(window, 500),
            confidence=confidence,
            timeframe=timeframe,
            lookback_bars=min(lookback_bars, 2000),
            horizon_days=horizon_days,
            notional_usdt=notional_usdt,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class CryptoWorkflowStep(BaseModel):
    id: str
    enabled: bool = True
    order: int = 0
    params: dict[str, Any] = Field(default_factory=dict)


class CryptoWorkflowTemplateBody(BaseModel):
    id: str | None = None
    name: str = "自定义 Workflow"
    symbol_default: str = "BTC"
    timeframe: str = "1d"
    data_dir: str = "data/crypto"
    steps: list[CryptoWorkflowStep] = Field(default_factory=list)


class CryptoWorkflowRunRequest(BaseModel):
    symbol: str | None = None
    timeframe: str | None = None
    template_id: str | None = None
    template: CryptoWorkflowTemplateBody | None = None
    steps: list[CryptoWorkflowStep] | None = None
    data_dir: str = "data/crypto"
    refresh_ohlcv: bool = True


class CryptoNewsConfigBody(BaseModel):
    enabled: bool | None = None
    min_score: int | None = Field(None, ge=0, le=100)
    llm_top_n: int | None = Field(None, ge=1, le=50)
    attach_to_analysis_cycle: bool | None = None
    digest_max_age_minutes: int | None = Field(None, ge=1, le=1440)
    feeds: list[dict[str, Any]] | None = None
    web_search: dict[str, Any] | None = None


class CryptoNewsScanRequest(BaseModel):
    data_dir: str = "data"
    feed_ids: list[str] | None = None


@router.get("/workflow/steps")
def crypto_workflow_steps_get() -> dict[str, Any]:
    from quant_rd_tool.crypto_workflow import list_step_catalog

    return {"steps": list_step_catalog()}


@router.get("/workflow/templates")
def crypto_workflow_templates_get(data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.crypto_workflow_storage import list_templates

    items = list_templates(data_dir)
    return {"count": len(items), "templates": items}


@router.post("/workflow/templates")
def crypto_workflow_templates_post(
    body: CryptoWorkflowTemplateBody,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    from quant_rd_tool.crypto_workflow import normalize_template_steps
    from quant_rd_tool.crypto_workflow_storage import upsert_template

    payload = body.model_dump()
    payload["data_dir"] = data_dir
    payload["steps"] = normalize_template_steps([s.model_dump() for s in body.steps] or [])
    tpl = upsert_template(data_dir, payload)
    return {"ok": True, "template": tpl}


@router.put("/workflow/templates/{template_id}")
def crypto_workflow_templates_put(
    template_id: str,
    body: CryptoWorkflowTemplateBody,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    from quant_rd_tool.crypto_workflow import normalize_template_steps
    from quant_rd_tool.crypto_workflow_storage import upsert_template

    payload = body.model_dump()
    payload["id"] = template_id
    payload["data_dir"] = data_dir
    payload["steps"] = normalize_template_steps([s.model_dump() for s in body.steps] or [])
    tpl = upsert_template(data_dir, payload)
    return {"ok": True, "template": tpl}


@router.delete("/workflow/templates/{template_id}")
def crypto_workflow_templates_delete(template_id: str, data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.crypto_workflow_storage import delete_template

    ok = delete_template(data_dir, template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}


@router.post("/workflow/templates/{template_id}/duplicate")
def crypto_workflow_templates_duplicate(
    template_id: str,
    data_dir: str = "data/crypto",
    name: str | None = None,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_workflow_storage import duplicate_template

    tpl = duplicate_template(data_dir, template_id, name=name)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True, "template": tpl}


@router.post("/workflow/run")
def crypto_workflow_run_post(req: CryptoWorkflowRunRequest) -> dict[str, Any]:
    from quant_rd_tool.crypto_workflow import resolve_template_for_run, run_workflow

    data_dir = req.data_dir
    try:
        tpl = resolve_template_for_run(
            data_dir=data_dir,
            template_id=req.template_id,
            template=req.template.model_dump() if req.template else None,
            timeframe=req.timeframe,
            steps=[s.model_dump() for s in req.steps] if req.steps else None,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    symbol = (req.symbol or tpl.get("symbol_default") or "BTC").strip().upper()
    try:
        return run_workflow(
            symbol=symbol,
            template=tpl,
            data_dir=data_dir,
            refresh_ohlcv=req.refresh_ohlcv,
            save=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/workflow/runs")
def crypto_workflow_runs_get(
    data_dir: str = "data/crypto",
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    from quant_rd_tool.crypto_workflow_storage import list_runs

    items = list_runs(data_dir, limit=limit)
    return {"count": len(items), "runs": items}


@router.get("/workflow/runs/{run_id}")
def crypto_workflow_run_get(run_id: str, data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.crypto_workflow_storage import load_run

    run = load_run(data_dir, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/news/digest")
def crypto_news_digest_get(data_dir: str = "data") -> dict[str, Any]:
    from quant_rd_tool.crypto_news_config import resolve_news_data_dir_for_api
    from quant_rd_tool.crypto_news_storage import empty_digest, load_digest

    root = resolve_news_data_dir_for_api(data_dir)
    digest = load_digest(root)
    return digest if digest else empty_digest()


@router.get("/news/items")
def crypto_news_items_get(
    data_dir: str = "data",
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    from quant_rd_tool.crypto_news_config import resolve_news_data_dir_for_api
    from quant_rd_tool.crypto_news_storage import load_items

    root = resolve_news_data_dir_for_api(data_dir)
    items = load_items(root, limit=limit)
    return {"count": len(items), "items": items}


@router.post("/news/scan")
def crypto_news_scan_post(req: CryptoNewsScanRequest) -> dict[str, Any]:
    from quant_rd_tool.crypto_news_config import resolve_news_data_dir_for_api
    from quant_rd_tool.crypto_news_scheduler import run_news_cycle

    root = resolve_news_data_dir_for_api(req.data_dir)
    try:
        return run_news_cycle(data_dir=root, feed_ids=req.feed_ids)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/news/search-usage")
def crypto_news_search_usage_get(data_dir: str = "data") -> dict[str, Any]:
    from quant_rd_tool.crypto_news_config import get_crypto_news_config, resolve_news_data_dir_for_api
    from quant_rd_tool.crypto_news_search import resolve_web_search_provider
    from quant_rd_tool.crypto_news_search_usage import usage_summary

    root = resolve_news_data_dir_for_api(data_dir)
    cfg = get_crypto_news_config()
    ws = cfg.get("web_search") if isinstance(cfg.get("web_search"), dict) else {}
    provider = resolve_web_search_provider(ws)
    return usage_summary(root, ws, provider=provider)


@router.get("/news/config")
def crypto_news_config_get(data_dir: str | None = None) -> dict[str, Any]:
    from quant_rd_tool.crypto_news_config import get_crypto_news_config, resolve_news_data_dir_for_api
    from quant_rd_tool.crypto_news_search import resolve_web_search_provider
    from quant_rd_tool.crypto_news_search_usage import usage_summary

    cfg = get_crypto_news_config()
    if data_dir:
        root = resolve_news_data_dir_for_api(data_dir)
        ws = cfg.get("web_search") if isinstance(cfg.get("web_search"), dict) else {}
        provider = resolve_web_search_provider(ws)
        cfg["search_usage"] = usage_summary(root, ws, provider=provider)
    return cfg


@router.post("/news/config")
def crypto_news_config_save(body: CryptoNewsConfigBody) -> dict[str, Any]:
    from quant_rd_tool.crypto_news_config import save_crypto_news_config

    return save_crypto_news_config(
        enabled=body.enabled,
        min_score=body.min_score,
        llm_top_n=body.llm_top_n,
        attach_to_analysis_cycle=body.attach_to_analysis_cycle,
        digest_max_age_minutes=body.digest_max_age_minutes,
        feeds=body.feeds,
        web_search=body.web_search,
    )


class CryptoZiplineSyncRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTC", "ETH"])
    data_dir: str = "data/crypto"
    backfill_days: int = Field(90, ge=7, le=365)
    exchange_id: str = "binance"
    timeframe: str = "15m"


class CryptoZiplineComboLeg(BaseModel):
    strategy: str
    params: dict[str, Any] | None = None
    weight: float = Field(1.0, gt=0)


class CryptoZiplineBacktestRequest(BaseModel):
    symbol: str = "BTC"
    strategy: str = "ma_crossover"
    start: str = "2026-01-01"
    end: str = "2026-06-03"
    capital_base: float = Field(100_000.0, gt=0)
    data_dir: str = "data/crypto"
    strategy_params: dict[str, Any] | None = None
    lookback_days: int = Field(90, ge=7, le=365)
    sync_first: bool = False
    engine: str = Field("auto", pattern="^(auto|pandas|zipline)$")
    force_reingest: bool = False
    timeframe: str = "15m"
    strategy_combo: list[CryptoZiplineComboLeg] | None = None
    combo_mode: str = Field("vote", pattern="^(vote|and|or|weighted)$")
    with_options_context: bool = Field(
        False,
        description="并入 Binance 期权 IV 与策略建议作为回测上下文（不影响回测逻辑）",
    )
    with_options_backtest: bool = Field(
        False,
        description="在现货回测上叠加期权腿（BS+IV 历史），输出组合净值",
    )
    options_overlay: str = Field(
        "auto",
        description="auto（strategy_pack）| call_overlay | put_hedge | short_straddle_iv | covered_call | long_straddle",
    )
    options_backtest_params: dict[str, Any] | None = None
    commission_pct: float | None = Field(
        None, ge=0, le=0.05, description="单边手续费比例，默认 0.001（0.1%）"
    )
    slippage_pct: float | None = Field(
        None, ge=0, le=0.05, description="单边滑点比例，默认 0.0005（0.05%）"
    )


@router.get("/zipline/status")
def crypto_zipline_status_get(
    data_dir: str = "data/crypto",
    symbols: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_zipline_lab import lab_status

    sym_list = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    return lab_status(data_dir, sym_list, timeframe=timeframe)


@router.get("/zipline/strategies")
def crypto_zipline_strategies_get() -> dict[str, Any]:
    from quant_rd_tool.crypto_zipline_lab import get_strategies

    return {"strategies": get_strategies()}


@router.post("/zipline/setup-venv")
def crypto_zipline_setup_venv_post() -> dict[str, Any]:
    """Create .venv-zipline with zipline-reloaded (numpy<2, pandas<2.2)."""
    from quant_rd_tool.crypto_zipline_env import ensure_zipline_venv, zipline_venv_ready

    try:
        py = ensure_zipline_venv()
        ok, err = zipline_venv_ready()
        return {"ok": ok, "python": str(py), "error": err}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/zipline/sync")
def crypto_zipline_sync_post(req: CryptoZiplineSyncRequest) -> dict[str, Any]:
    from quant_rd_tool.crypto_zipline_lab import sync_ohlcv_for_lab

    try:
        return sync_ohlcv_for_lab(
            req.symbols,
            data_dir=req.data_dir,
            timeframe=req.timeframe,
            backfill_days=req.backfill_days,
            exchange_id=req.exchange_id,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/zipline/backtest")
def crypto_zipline_backtest_post(req: CryptoZiplineBacktestRequest) -> dict[str, Any]:
    from quant_rd_tool.crypto_zipline_lab import run_lab_backtest

    combo_legs = None
    if req.strategy_combo:
        combo_legs = [leg.model_dump() for leg in req.strategy_combo]

    try:
        return run_lab_backtest(
            symbol=req.symbol,
            data_dir=req.data_dir,
            strategy_id=req.strategy,
            start=req.start,
            end=req.end,
            capital_base=req.capital_base,
            strategy_params=req.strategy_params,
            lookback_days=req.lookback_days,
            sync_first=req.sync_first,
            engine=req.engine,
            force_reingest=req.force_reingest,
            timeframe=req.timeframe,
            strategy_combo=combo_legs,
            combo_mode=req.combo_mode,
            with_options_context=req.with_options_context,
            with_options_backtest=req.with_options_backtest,
            options_overlay=req.options_overlay,
            options_backtest_params=req.options_backtest_params,
            commission_pct=req.commission_pct,
            slippage_pct=req.slippage_pct,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/zipline/runs")
def crypto_zipline_runs_get(data_dir: str = "data/crypto", limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    from quant_rd_tool.crypto_zipline_storage import list_runs

    items = list_runs(data_dir, limit=limit)
    return {"count": len(items), "runs": items}


@router.get("/zipline/runs/{run_id}")
def crypto_zipline_run_get(run_id: str, data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.crypto_zipline_storage import load_run

    run = load_run(data_dir, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/zipline/data/export")
def crypto_zipline_data_export(
    symbol: str = Query("BTC"),
    data_dir: str = "data/crypto",
    timeframe: str = "15m",
    start: str | None = None,
    end: str | None = None,
    lookback_days: int = Query(90, ge=7, le=365),
    format: str = Query("csv", pattern="^(csv|zip)$"),
    run_id: str | None = None,
) -> Response:
    from quant_rd_tool.crypto_zipline_export import (
        build_export_zip,
        export_filename,
        export_ohlcv_dataframe,
    )

    try:
        if format == "zip":
            content = build_export_zip(
                symbol,
                data_dir=data_dir,
                timeframe=timeframe,
                start=start,
                end=end,
                lookback_days=lookback_days,
                run_id=run_id,
            )
            fname = export_filename(symbol, timeframe, ext="zip")
            return Response(
                content=content,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{fname}"'},
            )
        df = export_ohlcv_dataframe(
            symbol,
            data_dir=data_dir,
            timeframe=timeframe,
            start=start,
            end=end,
            lookback_days=lookback_days,
        )
        fname = export_filename(symbol, timeframe, ext="csv")
        return Response(
            content=df.to_csv(index=False),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class OptionsVolConfigBody(BaseModel):
    symbols: list[str] | None = None
    lookback_days: int | None = Field(None, ge=7, le=365)
    iv_percentile_threshold: float | None = Field(None, ge=50, le=99)
    iv_change_24h_threshold: float | None = Field(None, ge=1, le=100)


class OptionsSpreadAlertConfigBody(BaseModel):
    enabled: bool | None = None
    elevated_pp: float | None = Field(None, ge=0.5, le=50)
    hot_pp: float | None = Field(None, ge=1, le=100)
    cooldown_minutes: int | None = Field(None, ge=1, le=1440)
    symbols: list[str] | None = None
    webhook_on_alert: bool | None = None
    bark_on_alert: bool | None = None


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
    from quant_rd_tool.crypto_options_compare import build_venue_compare_scan
    from quant_rd_tool.crypto_options_strategies import build_strategy_pack

    compare = build_venue_compare_scan(
        sym_list or scan.get("config", {}).get("symbols"),
        data_dir=data_dir,
    )
    compare_map = {i["base"]: i for i in compare.get("items") or []}
    for item in scan.get("items") or []:
        if isinstance(item, dict) and item.get("atm_iv") is not None:
            base = item.get("base")
            vc = compare_map.get(base) if base else None
            if vc:
                item["venue_compare"] = vc
            item["strategy_pack"] = build_strategy_pack(
                scan_item=item,
                venue_compare=vc,
            )
    return {**scan, "advice_pack": advice, "venue_compare_pack": compare}


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


@router.get("/options/compare")
def crypto_options_venue_compare_scan(
    symbols: str | None = None,
    base: str | None = None,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_compare import (
        build_venue_compare,
        build_venue_compare_scan,
    )

    try:
        if base:
            return build_venue_compare(base.strip().upper())
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
        return build_venue_compare_scan(sym_list, data_dir=data_dir)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/options/compare/term-structure")
def crypto_options_venue_compare_term_structure(base: str) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_compare import build_term_structure_compare

    try:
        return build_term_structure_compare(base.strip().upper())
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/options/compare/common-expiries")
def crypto_options_common_expiries(base: str, min_dte: int = 7) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_compare import list_common_expiries

    try:
        return list_common_expiries(base.strip().upper(), min_dte=min_dte)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/options/compare/spread-history")
def crypto_options_spread_history(
    symbol: str,
    data_dir: str = "data/crypto",
    limit: int = 120,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_spread_history import load_spread_history

    items = load_spread_history(symbol, data_dir=data_dir, limit=min(limit, 500))
    return {"symbol": symbol.upper(), "count": len(items), "items": items}


@router.get("/options/compare/aligned")
def crypto_options_aligned_compare(
    base: str,
    expiry_date: str | None = None,
    n: int = 5,
    min_dte: int = 7,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_compare import build_aligned_expiry_compare

    try:
        return build_aligned_expiry_compare(
            base.strip().upper(),
            expiry_date=expiry_date,
            n=n,
            min_dte=min_dte,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/options/greeks")
def crypto_options_greeks(
    base: str,
    expiry_date: str | None = None,
    n: int = 3,
    min_dte: int = 7,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_greeks import build_greeks_chain

    try:
        return build_greeks_chain(
            base.strip().upper(),
            expiry_date=expiry_date,
            n=n,
            min_dte=min_dte,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/options/greeks/portfolio")
def crypto_options_portfolio_greeks(
    base: str,
    spot_pct: float = 0.75,
    options_pct: float = 0.25,
    overlay_id: str | None = None,
    strategy_index: int = 0,
    use_strategy_pack: bool = False,
    spot_stance: str = "中性",
    venue: str = "binance",
    capital: float = 100_000.0,
    expiry_date: str | None = None,
    scale_mode: str = "notional",
    persist: bool = False,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_portfolio_greeks import build_portfolio_greeks_report

    base_u = base.strip().upper()
    pack = None
    if use_strategy_pack:
        from quant_rd_tool.crypto_options_strategies import build_strategy_pack
        from quant_rd_tool.crypto_options_vol_scan import run_volatility_scan

        scan = run_volatility_scan(symbols=[base_u], persist_snapshot=False)
        item = next((i for i in scan.get("items") or [] if i.get("base") == base_u), None)
        if item:
            pack = build_strategy_pack(scan_item=item, spot_stance=spot_stance)

    mode = scale_mode if scale_mode in ("notional", "margin") else "notional"
    try:
        return build_portfolio_greeks_report(
            base_u,
            spot_pct=spot_pct,
            options_pct=options_pct,
            overlay_id=overlay_id,
            strategy_pack=pack,
            strategy_index=strategy_index,
            venue=venue,  # type: ignore[arg-type]
            capital=capital,
            expiry_date=expiry_date,
            scale_mode=mode,  # type: ignore[arg-type]
            persist=persist,
            data_dir=data_dir,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/options/greeks/portfolio/multi")
def crypto_options_portfolio_greeks_multi(
    bases: str,
    weights: str | None = None,
    spot_pct: float = 0.75,
    options_pct: float = 0.25,
    overlay_id: str | None = None,
    use_strategy_pack: bool = False,
    spot_stance: str = "中性",
    venue: str = "binance",
    capital: float = 100_000.0,
    scale_mode: str = "notional",
    persist: bool = False,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_portfolio_greeks import build_multi_from_lists

    base_list = [b.strip().upper() for b in bases.split(",") if b.strip()]
    if not base_list:
        raise HTTPException(status_code=400, detail="bases required")
    w_list = None
    if weights:
        try:
            w_list = [float(x.strip()) for x in weights.split(",") if x.strip()]
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid weights") from e
    mode = scale_mode if scale_mode in ("notional", "margin") else "notional"
    try:
        return build_multi_from_lists(
            base_list,
            weights=w_list,
            capital=capital,
            spot_pct=spot_pct,
            options_pct=options_pct,
            overlay_id=overlay_id,
            venue=venue,  # type: ignore[arg-type]
            scale_mode=mode,  # type: ignore[arg-type]
            use_strategy_pack=use_strategy_pack,
            spot_stance=spot_stance,
            persist=persist,
            data_dir=data_dir,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/options/greeks/portfolio/history")
def crypto_options_portfolio_greeks_history(
    portfolio_id: str | None = None,
    bases: str | None = None,
    limit: int = 120,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_portfolio_greeks_history import (
        load_greeks_history,
        portfolio_id_from_bases,
    )

    if portfolio_id:
        pid = portfolio_id.strip()
    elif bases:
        pid = portfolio_id_from_bases([b.strip() for b in bases.split(",") if b.strip()])
    else:
        raise HTTPException(status_code=400, detail="portfolio_id or bases required")
    items = load_greeks_history(pid, data_dir=data_dir, limit=limit)
    return {"portfolio_id": pid, "count": len(items), "items": items}


@router.get("/options/compare/spread-alerts/config")
def crypto_options_spread_alerts_config_get(data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.crypto_options_spread_alerts import get_spread_alert_config

    return get_spread_alert_config(data_dir)


@router.post("/options/compare/spread-alerts/config")
def crypto_options_spread_alerts_config_save(
    body: OptionsSpreadAlertConfigBody,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_spread_alerts import save_spread_alert_config

    return save_spread_alert_config(
        data_dir=data_dir,
        enabled=body.enabled,
        elevated_pp=body.elevated_pp,
        hot_pp=body.hot_pp,
        cooldown_minutes=body.cooldown_minutes,
        symbols=body.symbols,
        webhook_on_alert=body.webhook_on_alert,
        bark_on_alert=body.bark_on_alert,
    )


@router.get("/options/compare/spread-alerts/log")
def crypto_options_spread_alerts_log(limit: int = 50) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_spread_alerts import tail_spread_alert_log

    items = tail_spread_alert_log(limit=min(limit, 200))
    return {"count": len(items), "items": items}


@router.post("/options/compare/spread-alerts/test")
def crypto_options_spread_alerts_test(data_dir: str = "data/crypto") -> dict[str, Any]:
    from quant_rd_tool.crypto_options_spread_alerts import send_test_spread_alert

    try:
        return send_test_spread_alert(data_dir=data_dir)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/options/expiries")
def crypto_options_expiries(
    base: str,
    min_dte: int = 7,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_surface import list_expiries

    try:
        return list_expiries(base, min_dte=min_dte)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/options/term-structure")
def crypto_options_term_structure(
    base: str,
    min_dte: int = 7,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_surface import build_term_structure

    try:
        return build_term_structure(base, min_dte=min_dte)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/options/iv-skew")
def crypto_options_iv_skew(
    base: str,
    expiry: str | None = None,
    min_dte: int = 7,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_surface import build_iv_skew

    try:
        return build_iv_skew(base, expiry_iso=expiry, min_dte=min_dte)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/options/strike-probability")
def crypto_options_strike_probability(
    base: str,
    n: int | None = None,
    expiry: str | None = None,
    data_dir: str = "data/crypto",
    spot_stance: str | None = None,
    iv_alert_level: str | None = None,
    iv_percentile: float | None = None,
    full_chain: bool = False,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_strike_probs import build_strike_probability_report

    try:
        return build_strike_probability_report(
            base,
            n=n,
            data_dir=data_dir,
            expiry_iso=expiry,
            spot_stance=spot_stance,
            iv_alert_level=iv_alert_level,
            iv_percentile=iv_percentile,
            full_chain=full_chain,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
