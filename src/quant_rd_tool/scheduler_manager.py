"""In-process scheduler registry: list / start / stop crypto schedule jobs."""

from __future__ import annotations

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

logger = logging.getLogger(__name__)

JobStatus = Literal["stopped", "running", "error"]


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
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        self.symbols = [s.strip().upper() for s in self.symbols if s.strip()]
        if not self.name:
            self.name = f"{'-'.join(self.symbols).lower()} {self.timeframe}"
        if not self.id:
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
        if run_immediately and cfg.symbols:
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
            running.record.started_at = datetime.now(UTC).isoformat()
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
        if precheck_connectivity and cfg.symbols:
            from quant_rd_tool.ccxt_connectivity import require_connectivity

            require_connectivity(
                cfg.exchange_id,
                test_ohlcv=True,
                symbol=cfg.symbols[0],
                timeframe=cfg.timeframe,
            )
        results = run_scheduled_cycle(
            cfg.symbols,
            data_dir=cfg.data_dir,
            timeframe=cfg.timeframe,
            backfill_days=cfg.backfill_days,
            with_ml=cfg.with_ml,
            ml_algorithm=cfg.ml_algorithm,
            exchange_id=cfg.exchange_id,
        )
        with self._lock:
            running = self._jobs[job_id]
            running.record.run_count += 1
            running.record.last_run_at = datetime.now(UTC).isoformat()
            running.record.last_error = _first_error(results)
            running.record.last_cycle_summary = _summarize_results(results)
            record = running.record
            self._save()
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
                results = run_scheduled_cycle(
                    cfg.symbols,
                    data_dir=cfg.data_dir,
                    timeframe=cfg.timeframe,
                    backfill_days=cfg.backfill_days,
                    with_ml=cfg.with_ml,
                    ml_algorithm=cfg.ml_algorithm,
                    exchange_id=cfg.exchange_id,
                    precheck_connectivity=False,
                )
                with self._lock:
                    running = self._jobs.get(job_id)
                    if not running:
                        break
                    running.record.run_count += 1
                    running.record.last_run_at = datetime.now(UTC).isoformat()
                    running.record.last_error = _first_error(results)
                    running.record.last_cycle_summary = _summarize_results(results)
                    running.record.status = "running"
                    record = running.record
                    self._save()
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

        summary.append(
            {
                "symbol": normalize_symbol(pair),
                "pair": pair,
                "stance": sig.get("stance"),
                "action": sig.get("action"),
                "new_bars": sync.get("new_bars", 0),
            }
        )
    return summary


_manager: SchedulerManager | None = None


def get_scheduler_manager(data_dir: str = "data/crypto") -> SchedulerManager:
    global _manager
    if _manager is None:
        registry = Path(data_dir) / "schedules.json"
        _manager = SchedulerManager(registry)
    return _manager


def reset_scheduler_manager() -> None:
    """Test helper."""
    global _manager
    _manager = None
