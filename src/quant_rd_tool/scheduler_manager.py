"""In-process scheduler registry: list / start / stop crypto schedule jobs."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
import logging
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_scheduler import run_scheduled_cycle
from quant_rd_tool.stock_scheduler import run_stock_scheduled_cycle

logger = logging.getLogger(__name__)

JobStatus = Literal["stopped", "running", "error"]
StockJobType = Literal["stock_qlib", "stock_watchlist", "stock_announcements"]
CryptoJobType = Literal["analysis", "news", "polymarket_arb"]
JobType = Literal["analysis", "news", "stock_qlib", "stock_watchlist", "stock_announcements", "polymarket_arb"]


@dataclass
class ScheduleJobConfig:
    symbols: list[str]
    timeframe: str = "5m"
    interval_minutes: int = 30
    backfill_days: int = 90
    data_dir: str = "data/crypto"
    with_ml: bool = True
    ml_algorithm: str = "both"
    exchange_id: cxt.ExchangeId = "binance"
    name: str = ""
    id: str = ""
    job_type: JobType = "analysis"
    years: int = 2
    with_openbb: bool = False
    use_watchlist: bool = False
    created_at: str = field(default_factory=lambda: now_iso())

    def __post_init__(self) -> None:
        from quant_rd_tool.akshare_data import to_ak_code

        if self.job_type in ("stock_qlib", "stock_watchlist", "stock_announcements"):
            self.symbols = [to_ak_code(s) for s in self.symbols if str(s).strip()]
        else:
            self.symbols = [s.strip().upper() for s in self.symbols if s.strip()]
        if self.job_type in ("stock_watchlist", "stock_announcements"):
            self.use_watchlist = True
        if not self.name:
            if self.job_type == "news":
                self.name = "crypto news scan"
            elif self.job_type == "polymarket_arb":
                self.name = "Polymarket 套利扫描"
            elif self.job_type == "stock_watchlist":
                self.name = "自选 qlib 刷新"
            elif self.job_type == "stock_announcements":
                self.name = "公告雷达扫描"
            elif self.job_type == "stock_qlib":
                self.name = f"{'-'.join(self.symbols).lower() or 'stocks'} 1d"
            else:
                self.name = f"{'-'.join(self.symbols).lower()} {self.timeframe}"
        if not self.id:
            if self.job_type == "news":
                self.id = "news-scan"
            elif self.job_type == "polymarket_arb":
                self.id = "polymarket-arb"
            elif self.job_type == "stock_watchlist":
                self.id = "watchlist-1d"
            elif self.job_type == "stock_announcements":
                self.id = "announcements-watchlist"
            elif self.job_type == "stock_qlib":
                self.id = _slug_id(self.symbols or ["stocks"], "1d")
            else:
                self.id = _slug_id(self.symbols, self.timeframe)


@dataclass
class ScheduleJobRecord:
    config: ScheduleJobConfig
    status: JobStatus = "stopped"
    run_count: int = 0
    last_run_at: str | None = None
    last_error: str | None = None
    last_cycle_summary: list[dict[str, Any]] | None = None
    started_at: str | None = None
    next_run_at: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        out = asdict(self.config)
        out.update(
            {
                "status": self.status,
                "run_count": self.run_count,
                "last_run_at": self.last_run_at,
                "last_error": self.last_error,
                "started_at": self.started_at,
                "next_run_at": self.next_run_at,
                "last_cycle_summary": self.last_cycle_summary,
            }
        )
        return out


class _RunningJob:
    def __init__(self, record: ScheduleJobRecord) -> None:
        self.record = record
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None


def _is_stock_job(cfg: ScheduleJobConfig) -> bool:
    return cfg.job_type in ("stock_qlib", "stock_watchlist", "stock_announcements") or str(
        cfg.data_dir
    ).rstrip("/").endswith("stocks")


def _run_polymarket_cycle() -> list[dict[str, Any]]:
    from quant_rd_tool.crypto_polymarket_scheduler import run_polymarket_scan_cycle

    result = run_polymarket_scan_cycle()
    return [result]


def _run_analysis_cycle(cfg: ScheduleJobConfig) -> list[dict[str, Any]]:
    if cfg.job_type == "news":
        raise ValueError("use _run_news_cycle for news jobs")
    if cfg.job_type == "polymarket_arb":
        return _run_polymarket_cycle()
    if _is_stock_job(cfg):
        return run_stock_scheduled_cycle(
            cfg.symbols,
            data_dir=cfg.data_dir,
            years=cfg.years,
            with_ml=cfg.with_ml,
            ml_algorithm=cfg.ml_algorithm,
            with_openbb=cfg.with_openbb,
            use_watchlist=cfg.use_watchlist or cfg.job_type == "stock_watchlist",
        )
    return run_scheduled_cycle(
        cfg.symbols,
        data_dir=cfg.data_dir,
        timeframe=cfg.timeframe,
        backfill_days=cfg.backfill_days,
        with_ml=cfg.with_ml,
        ml_algorithm=cfg.ml_algorithm,
        exchange_id=cfg.exchange_id,
        precheck_connectivity=False,
    )


def _slug_id(symbols: list[str], timeframe: str) -> str:
    base = "-".join(s.lower() for s in symbols) + f"-{timeframe.replace('/', '')}"
    return re.sub(r"[^a-z0-9\-]", "-", base)


class SchedulerManager:
    """Thread-backed scheduler registry with JSON persistence."""

    def __init__(self, registry_path: str | Path) -> None:
        self.registry_path = Path(registry_path)
        self._lock = threading.RLock()
        self._jobs: dict[str, _RunningJob] = {}
        self._load()

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.record.to_public_dict() for job in self._jobs.values()]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.record.to_public_dict() if job else None

    def add_job(
        self,
        config: ScheduleJobConfig,
        *,
        auto_start: bool = False,
        unique_id: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            if config.id in self._jobs:
                if not unique_id:
                    raise ValueError(f"任务已存在: {config.id}")
                config.id = self._ensure_unique_id(config.id)
            self._jobs[config.id] = _RunningJob(ScheduleJobRecord(config=config))
            self._save()
            record = self._jobs[config.id].record.to_public_dict()
        if auto_start:
            return self.start_job(config.id)
        return record

    def start_job(self, job_id: str, *, run_immediately: bool = True) -> dict[str, Any]:
        with self._lock:
            running = self._jobs.get(job_id)
            if not running:
                raise KeyError(f"未找到任务: {job_id}")
            cfg = running.record.config
        if run_immediately and cfg.symbols and cfg.job_type not in (
            "news",
            "stock_watchlist",
            "stock_announcements",
            "polymarket_arb",
        ) and not (_is_stock_job(cfg) and not cfg.symbols):
            if not _is_stock_job(cfg):
                from quant_rd_tool.ccxt_connectivity import require_connectivity

                require_connectivity(
                    cfg.exchange_id,
                    test_ohlcv=True,
                    symbol=cfg.symbols[0],
                    timeframe=cfg.timeframe,
                )
        with self._lock:
            running = self._jobs.get(job_id)
            if not running:
                raise KeyError(f"未找到任务: {job_id}")
            if running.thread and running.thread.is_alive():
                return running.record.to_public_dict()
            running.stop_event.clear()
            running.record.status = "running"
            running.record.started_at = now_iso()
            running.record.last_error = None
            running.thread = threading.Thread(
                target=self._worker,
                args=(job_id, run_immediately),
                name=f"schedule-{job_id}",
                daemon=True,
            )
            running.thread.start()
            self._save()
            return running.record.to_public_dict()

    def stop_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            running = self._jobs.get(job_id)
            if not running:
                raise KeyError(f"未找到任务: {job_id}")
            running.stop_event.set()
            thread = running.thread
            record = running.record
        if thread and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            record.status = "stopped"
            record.started_at = None
            record.next_run_at = None
            self._save()
            return record.to_public_dict()

    def remove_job(self, job_id: str) -> dict[str, Any]:
        self.stop_job(job_id)
        with self._lock:
            running = self._jobs.pop(job_id, None)
            if not running:
                raise KeyError(f"未找到任务: {job_id}")
            payload = running.record.to_public_dict()
            self._save()
            return payload

    def run_once(self, job_id: str, *, precheck_connectivity: bool = True) -> dict[str, Any]:
        with self._lock:
            running = self._jobs.get(job_id)
            if not running:
                raise KeyError(f"未找到任务: {job_id}")
            cfg = running.record.config
        if precheck_connectivity and cfg.job_type not in (
            "news",
            "stock_watchlist",
            "stock_announcements",
            "polymarket_arb",
        ) and cfg.symbols:
            if not _is_stock_job(cfg):
                from quant_rd_tool.ccxt_connectivity import require_connectivity

                require_connectivity(
                    cfg.exchange_id,
                    test_ohlcv=True,
                    symbol=cfg.symbols[0],
                    timeframe=cfg.timeframe,
                )
        if cfg.job_type == "news":
            results = _run_news_cycle(cfg, job_id=job_id)
        elif cfg.job_type == "stock_announcements":
            results = _run_announcement_cycle(cfg, job_id=job_id)
        elif cfg.job_type == "polymarket_arb":
            results = _run_polymarket_cycle()
        else:
            results = _run_analysis_cycle(cfg)
        with self._lock:
            running = self._jobs[job_id]
            running.record.run_count += 1
            running.record.last_run_at = now_iso()
            if cfg.job_type == "news":
                running.record.last_error = _first_news_error(results)
                running.record.last_cycle_summary = _summarize_news_result(results)
            elif cfg.job_type == "stock_announcements":
                running.record.last_error = _first_announcement_error(results)
                running.record.last_cycle_summary = _summarize_announcement_result(results)
            elif cfg.job_type == "polymarket_arb":
                running.record.last_error = None
                running.record.last_cycle_summary = _summarize_polymarket_results(results)
            elif _is_stock_job(cfg):
                running.record.last_error = _first_error(results)
                running.record.last_cycle_summary = _summarize_stock_results(results)
            else:
                running.record.last_error = _first_error(results)
                running.record.last_cycle_summary = _summarize_results(results)
            record = running.record
            self._save()
        if cfg.job_type not in ("news", "stock_announcements"):
            self._evaluate_alerts(job_id, record)
        return {
            "job": record.to_public_dict(),
            "results": results,
        }

    def _worker(self, job_id: str, run_immediately: bool) -> None:
        import time

        while True:
            with self._lock:
                running = self._jobs.get(job_id)
                if not running or running.stop_event.is_set():
                    break
                cfg = running.record.config
                interval_s = max(cfg.interval_minutes * 60, 5)

            if run_immediately:
                run_immediately = False
            else:
                with self._lock:
                    running = self._jobs.get(job_id)
                    if running:
                        running.record.next_run_at = datetime.fromtimestamp(
                            datetime.now(UTC).timestamp() + interval_s,
                            tz=UTC,
                        ).isoformat()
                        self._save()
                if not _interruptible_sleep(interval_s, running.stop_event if running else threading.Event()):
                    break

            try:
                if cfg.job_type == "news":
                    results = _run_news_cycle(cfg, job_id=job_id)
                    last_error = _first_news_error(results)
                    summary = _summarize_news_result(results)
                elif cfg.job_type == "stock_announcements":
                    results = _run_announcement_cycle(cfg, job_id=job_id)
                    last_error = _first_announcement_error(results)
                    summary = _summarize_announcement_result(results)
                elif cfg.job_type == "polymarket_arb":
                    results = _run_polymarket_cycle()
                    last_error = None
                    summary = _summarize_polymarket_results(results)
                else:
                    results = _run_analysis_cycle(cfg)
                    last_error = _first_error(results)
                    if _is_stock_job(cfg):
                        summary = _summarize_stock_results(results)
                    else:
                        summary = _summarize_results(results)
                with self._lock:
                    running = self._jobs.get(job_id)
                    if not running:
                        break
                    running.record.run_count += 1
                    running.record.last_run_at = now_iso()
                    running.record.last_error = last_error
                    running.record.last_cycle_summary = summary
                    running.record.status = "running"
                    record = running.record
                    self._save()
                if cfg.job_type not in ("news", "stock_announcements"):
                    self._evaluate_alerts(job_id, record)
            except Exception as e:
                logger.exception("Schedule job %s failed", job_id)
                with self._lock:
                    running = self._jobs.get(job_id)
                    if not running:
                        break
                    running.record.status = "error"
                    running.record.last_error = str(e)
                    record = running.record
                    self._save()
                self._evaluate_alerts(job_id, record)

            with self._lock:
                running = self._jobs.get(job_id)
                if not running or running.stop_event.is_set():
                    break

        with self._lock:
            running = self._jobs.get(job_id)
            if running and running.record.status != "error":
                running.record.status = "stopped"
                running.record.started_at = None
                running.record.next_run_at = None
                self._save()

    def _evaluate_alerts(self, job_id: str, record: ScheduleJobRecord) -> None:
        try:
            from quant_rd_tool.schedule_alerts import evaluate_after_cycle

            evaluate_after_cycle(
                job_id,
                last_error=record.last_error,
                last_cycle_summary=record.last_cycle_summary,
                status=record.status,
            )
        except Exception:
            logger.debug("Schedule alert evaluation failed for %s", job_id, exc_info=True)

    def check_stale_alerts(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [job.record.to_public_dict() for job in self._jobs.values()]
        from quant_rd_tool.schedule_alerts import evaluate_stale_jobs

        return evaluate_stale_jobs(jobs)

    def _ensure_unique_id(self, base: str) -> str:
        if base not in self._jobs:
            return base
        suffix = uuid.uuid4().hex[:6]
        candidate = f"{base}-{suffix}"
        while candidate in self._jobs:
            suffix = uuid.uuid4().hex[:6]
            candidate = f"{base}-{suffix}"
        return candidate

    def _load(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._jobs = {}
            return
        raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        jobs: dict[str, _RunningJob] = {}
        for item in raw.get("jobs", []):
            cfg_data = {k: v for k, v in item.items() if k in ScheduleJobConfig.__dataclass_fields__}
            meta = {k: v for k, v in item.items() if k not in ScheduleJobConfig.__dataclass_fields__}
            cfg = ScheduleJobConfig(**cfg_data)
            record = ScheduleJobRecord(
                config=cfg,
                status="stopped",
                run_count=int(meta.get("run_count") or 0),
                last_run_at=meta.get("last_run_at"),
                last_error=meta.get("last_error"),
                last_cycle_summary=meta.get("last_cycle_summary"),
            )
            jobs[cfg.id] = _RunningJob(record)
        self._jobs = jobs

    def _save(self) -> None:
        payload = {"jobs": [job.record.to_public_dict() for job in self._jobs.values()]}
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _interruptible_sleep(seconds: float, stop_event: threading.Event) -> bool:
    """Sleep in 1s slices; return False if stop requested."""
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if stop_event.is_set():
            return False
        time.sleep(min(1.0, end - time.monotonic()))
    return True


def _first_error(results: list[dict[str, Any]]) -> str | None:
    for r in results:
        if r.get("error"):
            return str(r["error"])
    return None


def _run_announcement_cycle(cfg: ScheduleJobConfig, *, job_id: str) -> dict[str, Any]:
    from quant_rd_tool.stock_announcement_scheduler import run_announcement_cycle

    return run_announcement_cycle(
        data_dir=cfg.data_dir,
        symbols=cfg.symbols,
        use_watchlist=cfg.use_watchlist or cfg.job_type == "stock_announcements",
        job_id=job_id,
    )


def _first_announcement_error(result: dict[str, Any]) -> str | None:
    if result.get("error"):
        return str(result["error"])
    errors = result.get("fetch_errors") or []
    if errors:
        return str(errors[0].get("error") or errors[0])
    return None


def _summarize_announcement_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    digest = result.get("digest") or {}
    top = digest.get("top_items") or []
    max_score = max((int(i.get("score") or 0) for i in top), default=0)
    return [
        {
            "job_type": "stock_announcements",
            "items_new": result.get("items_new", 0),
            "items_processed": result.get("items_processed", 0),
            "symbols_scanned": digest.get("symbols_scanned", 0),
            "top_score": max_score,
        }
    ]


def _run_news_cycle(cfg: ScheduleJobConfig, *, job_id: str) -> dict[str, Any]:
    from quant_rd_tool.crypto_news_config import resolve_news_data_dir
    from quant_rd_tool.crypto_news_scheduler import run_news_cycle

    return run_news_cycle(
        data_dir=resolve_news_data_dir(cfg.data_dir),
        job_id=job_id,
    )


def _first_news_error(result: dict[str, Any]) -> str | None:
    errors = result.get("fetch_errors") or []
    if errors:
        return str(errors[0])
    return None


def _summarize_news_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    digest = result.get("digest") or {}
    return [
        {
            "job_type": "news",
            "items_new": result.get("items_new", 0),
            "items_processed": result.get("items_processed", 0),
            "top_items": len(digest.get("top_items") or []),
            "market_stance": digest.get("market_stance"),
        }
    ]


def _summarize_polymarket_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from quant_rd_tool.crypto_polymarket_scheduler import summarize_polymarket_cycle

    if not results:
        return [{"job_type": "polymarket_arb", "markets_scanned": 0, "opportunities_count": 0}]
    row = summarize_polymarket_cycle(results[0])
    return [{"job_type": "polymarket_arb", **row}]


def _summarize_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for r in results:
        if r.get("error"):
            summary.append({"symbol": r.get("symbol"), "error": r.get("error")})
            continue
        sig = r.get("combined_signal") or {}
        sync = r.get("sync") or {}
        pair = r.get("pair", r.get("symbol"))
        from quant_rd_tool.schedule_alert_conditions import normalize_symbol

        opt = r.get("options_vol") if isinstance(r.get("options_vol"), dict) else {}
        advice = opt.get("advice") if isinstance(opt.get("advice"), dict) else {}
        entry: dict[str, Any] = {
            "symbol": normalize_symbol(pair),
            "pair": pair,
            "stance": sig.get("stance"),
            "action": sig.get("action"),
            "new_bars": sync.get("new_bars", 0),
            "iv_alert_level": opt.get("alert_level") if opt.get("enabled") else None,
            "options_stance": advice.get("stance"),
            "iv_percentile": opt.get("iv_percentile"),
            "iv_change_24h_pct": opt.get("iv_change_24h_pct"),
        }
        for key in (
            "var_enabled",
            "var_error",
            "var_pct",
            "var_usdt",
            "cvar_pct",
            "cvar_usdt",
            "var_95_pct",
            "var_99_pct",
            "var_95_usdt",
            "var_99_usdt",
            "parametric_var_pct",
            "mc_gbm_var_pct",
            "mc_t_var_pct",
        ):
            if r.get(key) is not None:
                entry[key] = r.get(key)
        summary.append(entry)
    return summary


def _summarize_stock_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for r in results:
        if r.get("error"):
            summary.append({"symbol": r.get("symbol") or r.get("code"), "error": r.get("error")})
            continue
        narrative = r.get("narrative") if isinstance(r.get("narrative"), dict) else {}
        inner = r.get("summary") if isinstance(r.get("summary"), dict) else {}
        code = r.get("code") or r.get("symbol")
        summary.append(
            {
                "symbol": r.get("symbol") or code,
                "code": code,
                "stance": narrative.get("stance") or inner.get("stance"),
                "action": inner.get("action"),
                "price": inner.get("price"),
                "market": "ashare",
            }
        )
    return summary


_manager: dict[str, SchedulerManager] = {}


def get_scheduler_manager(data_dir: str = "data/crypto") -> SchedulerManager:
    key = str(Path(data_dir).as_posix())
    mgr = _manager.get(key)
    if mgr is None:
        registry = Path(data_dir) / "schedules.json"
        mgr = SchedulerManager(registry)
        _manager[key] = mgr
    return mgr


def reset_scheduler_manager() -> None:
    """Test helper."""
    global _manager
    _manager = {}
