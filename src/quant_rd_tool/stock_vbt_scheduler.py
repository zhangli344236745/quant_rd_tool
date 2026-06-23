"""Daily pipeline scheduler for A-share VectorBT lab (ML screen → portfolio → signals)."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from quant_rd_tool.stock_vbt_lab import VBT_LAB_DIR, load_ohlcv, refresh_universe_data
from quant_rd_tool.stock_vbt_ml import screen_universe
from quant_rd_tool.stock_vbt_optuna import run_optuna_tune
from quant_rd_tool.stock_vbt_portfolio import optimize_portfolio
from quant_rd_tool.watchlist import Watchlist

logger = logging.getLogger(__name__)

SCHEDULER_DIR = VBT_LAB_DIR / "scheduler"
CONFIG_PATH = SCHEDULER_DIR / "config.json"
SIGNALS_PATH = VBT_LAB_DIR / "signals" / "latest.json"


@dataclass
class VbtSchedulerConfig:
    enabled: bool = False
    cron_hour: int = 18
    cron_minute: int = 0
    symbols: list[str] = field(default_factory=list)
    use_watchlist: bool = True
    strategy_id: str = "sma_cross"
    top_k: int = 5
    ml_algorithm: str = "lgb"
    portfolio_method: str = "max_sharpe"
    lookback_days: int = 252
    start: str = "2020-01-01"
    end: str = ""
    data_dir: str = "data/stocks"
    refresh_data: bool = True
    optuna_trials: int = 0


def _iso_now(now: datetime | None = None) -> str:
    dt = now or datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def load_config() -> VbtSchedulerConfig:
    if not CONFIG_PATH.is_file():
        return VbtSchedulerConfig()
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return VbtSchedulerConfig(
        enabled=bool(raw.get("enabled", False)),
        cron_hour=int(raw.get("cron_hour", 18)),
        cron_minute=int(raw.get("cron_minute", 0)),
        symbols=[str(s) for s in raw.get("symbols") or []],
        use_watchlist=bool(raw.get("use_watchlist", True)),
        strategy_id=str(raw.get("strategy_id", "sma_cross")),
        top_k=int(raw.get("top_k", 5)),
        ml_algorithm=str(raw.get("ml_algorithm", "lgb")),
        portfolio_method=str(raw.get("portfolio_method", "max_sharpe")),
        lookback_days=int(raw.get("lookback_days", 252)),
        start=str(raw.get("start", "2020-01-01")),
        end=str(raw.get("end") or ""),
        data_dir=str(raw.get("data_dir", "data/stocks")),
        refresh_data=bool(raw.get("refresh_data", True)),
        optuna_trials=int(raw.get("optuna_trials", 0)),
    )


def save_config(cfg: VbtSchedulerConfig) -> VbtSchedulerConfig:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    doc = asdict(cfg)
    doc["updated_at"] = _iso_now()
    CONFIG_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def run_daily_pipeline(cfg: VbtSchedulerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    symbols = list(cfg.symbols)
    if cfg.use_watchlist:
        wl = Watchlist().list_codes()
        if wl:
            symbols = wl
    if not symbols:
        raise ValueError("no symbols configured (set symbols or enable watchlist)")

    end = cfg.end or date.today().isoformat()
    refresh_report: dict[str, Any] | None = None
    if cfg.refresh_data:
        refresh_report = refresh_universe_data(
            symbols, cfg.start, end, data_dir=cfg.data_dir
        )

    ml = screen_universe(
        symbols=symbols,
        start=cfg.start,
        end=end,
        top_k=cfg.top_k,
        algorithm=cfg.ml_algorithm,  # type: ignore[arg-type]
        use_watchlist=False,
        data_dir=cfg.data_dir,
        refresh_data=False,
    )
    top_symbols = [row["symbol"] for row in ml.get("items", [])]
    if not top_symbols:
        raise ValueError("ML screen returned no candidates")

    tune_result: dict[str, Any] | None = None
    if cfg.optuna_trials >= 5:
        tune_result = run_optuna_tune(
            symbol=top_symbols[0],
            start=cfg.start,
            end=end,
            strategy_id=cfg.strategy_id,
            n_trials=cfg.optuna_trials,
            data_dir=cfg.data_dir,
            refresh_data=False,
        )

    port = optimize_portfolio(
        symbols=top_symbols,
        start=cfg.start,
        end=end,
        method=cfg.portfolio_method,  # type: ignore[arg-type]
        lookback_days=cfg.lookback_days,
        data_dir=cfg.data_dir,
    )

    payload = {
        "generated_at": _iso_now(),
        "strategy_id": cfg.strategy_id,
        "refresh": refresh_report,
        "tune": tune_result,
        "ml_run_id": ml.get("run_id"),
        "portfolio_run_id": port.get("run_id"),
        "ml_rankings": ml.get("items", []),
        "portfolio": port,
    }
    SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIGNALS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def get_latest_signals() -> dict[str, Any] | None:
    if not SIGNALS_PATH.is_file():
        return None
    return json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))


class VbtLabScheduler:
    def __init__(self) -> None:
        self._scheduler: BackgroundScheduler | None = None
        self._lock = threading.Lock()
        self._last_run_at: str | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._run_count = 0

    def status(self) -> dict[str, Any]:
        cfg = load_config()
        running = self._scheduler is not None and self._scheduler.running
        return {
            "running": running,
            "config": asdict(cfg),
            "last_run_at": self._last_run_at,
            "last_error": self._last_error,
            "last_result": self._last_result,
            "run_count": self._run_count,
            "latest_signals": get_latest_signals(),
        }

    def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        cfg = load_config()
        for key, val in updates.items():
            if not hasattr(cfg, key):
                continue
            setattr(cfg, key, val)
        save_config(cfg)
        if self._scheduler and self._scheduler.running:
            self._reschedule(cfg)
        return asdict(cfg)

    def start(self) -> dict[str, Any]:
        with self._lock:
            cfg = load_config()
            cfg.enabled = True
            save_config(cfg)
            if self._scheduler is None:
                self._scheduler = BackgroundScheduler()
            if not self._scheduler.running:
                self._scheduler.start()
            self._reschedule(cfg)
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            cfg = load_config()
            cfg.enabled = False
            save_config(cfg)
            if self._scheduler and self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                self._scheduler = None
        return self.status()

    def trigger(self) -> dict[str, Any]:
        return self._run_once()

    def _reschedule(self, cfg: VbtSchedulerConfig) -> None:
        if self._scheduler is None:
            return
        self._scheduler.remove_all_jobs()
        if not cfg.enabled:
            return
        self._scheduler.add_job(
            self._run_once,
            CronTrigger(hour=cfg.cron_hour, minute=cfg.cron_minute),
            id="vbt_daily_pipeline",
            replace_existing=True,
        )

    def _run_once(self) -> dict[str, Any]:
        self._last_run_at = _iso_now()
        try:
            result = run_daily_pipeline()
            self._run_count += 1
            self._last_result = {
                "generated_at": result.get("generated_at"),
                "ml_run_id": result.get("ml_run_id"),
                "portfolio_run_id": result.get("portfolio_run_id"),
                "tune_run_id": (result.get("tune") or {}).get("run_id"),
                "top_symbols": [r.get("symbol") for r in result.get("ml_rankings", [])],
            }
            self._last_error = None
            return result
        except Exception as e:  # noqa: BLE001 - surfaced via status
            self._last_error = str(e)
            logger.exception("VBT lab daily pipeline failed")
            raise


_SCHEDULER: VbtLabScheduler | None = None


def get_vbt_scheduler() -> VbtLabScheduler:
    global _SCHEDULER
    if _SCHEDULER is None:
        _SCHEDULER = VbtLabScheduler()
    return _SCHEDULER


def boot_vbt_scheduler_if_enabled() -> None:
    """Resume APScheduler when server restarts with enabled config."""
    cfg = load_config()
    if cfg.enabled:
        get_vbt_scheduler().start()
