"""Background worker for stock analysis / qlib jobs."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from quant_rd_tool import akshare_stocks as astk
from quant_rd_tool.job_results import save_job_result
from quant_rd_tool.job_store import JobStore
from quant_rd_tool.network_settings import apply_network_env
from quant_rd_tool.stock_analysis import analyze_stock
from quant_rd_tool.stock_storage import report_json_path, stock_root

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, store: JobStore, *, data_dir: str = "data/stocks") -> None:
        self.store = store
        self.data_dir = data_dir
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start_background(self, *, interval: float = 0.5) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            args=(interval,),
            name="quant-rd-job-runner",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self, interval: float) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("job runner loop error")
            self._stop.wait(interval)

    def run_once(self) -> bool:
        job = self.store.claim_next_queued()
        if not job:
            return False
        job_id = job["id"]
        try:
            apply_network_env()
            self.store.mark_progress(job_id, 0.1, message="starting")
            result_path, _result = self._execute(job)
            self.store.mark_done(job_id, result_path=result_path, message="done")
        except Exception as e:
            logger.exception("job %s failed", job_id)
            if self.store.schedule_retry(job_id, error=str(e)):
                logger.info("job %s scheduled for retry", job_id)
            else:
                self.store.mark_failed(job_id, error=str(e))
        return True

    def _execute(self, job: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        jtype = job["type"]
        code = job.get("code") or ""
        payload = job.get("payload") or {}
        job_id = job["id"]

        if jtype == "qlib_analyze":
            self.store.mark_progress(job_id, 0.3, message="qlib analyze")
            out = astk.run_qlib_stock_analysis(
                code,
                years=int(payload.get("years", 2)),
                refresh=bool(payload.get("refresh", True)),
                data_dir=str(payload.get("data_dir", self.data_dir)),
                with_ml=bool(payload.get("with_ml", True)),
                ml_algorithm=str(payload.get("ml_algorithm", "both")),
            )
            root = stock_root(self.data_dir, code)
            return str(report_json_path(root)), out

        if jtype == "analyze_stock":
            self.store.mark_progress(job_id, 0.3, message="analyze stock")
            out = analyze_stock(
                code,
                start_date=str(payload.get("start_date", "2020-01-01")),
                end_date=payload.get("end_date"),
                data_dir=str(payload.get("data_dir", self.data_dir)),
                refresh=bool(payload.get("refresh", False)),
                with_benchmark=bool(payload.get("with_benchmark", True)),
                benchmark=str(payload.get("benchmark", "sh000300")),
                with_ml=bool(payload.get("with_ml", True)),
                ml_algorithm=payload.get("ml_algorithm", "both"),
                data_provider=payload.get("data_provider", "auto"),
                with_openbb_enrichment=bool(payload.get("with_openbb_enrichment", True)),
            )
            root = stock_root(self.data_dir, code)
            return str(report_json_path(root)), out

        if jtype == "backtest_run":
            from quant_rd_tool.backtest_engine import run_backtest

            self.store.mark_progress(job_id, 0.2, message="backtest")
            symbols = payload.get("symbols")
            out = run_backtest(
                symbols,
                start_date=str(payload.get("start_date", "2023-01-01")),
                end_date=payload.get("end_date"),
                lookback=int(payload.get("lookback", 20)),
                topk=int(payload.get("topk", 3)),
                n_drop=int(payload.get("n_drop", 1)),
                initial_cash=float(payload.get("initial_cash", 1_000_000)),
                benchmark=str(payload.get("benchmark", "sh000300")),
                signal_mode=str(payload.get("signal_mode", "momentum")),
                ml_algorithm=payload.get("ml_algorithm", "lgb"),
                data_provider=payload.get("data_provider", "auto"),
            )
            snap = {
                "kind": "backtest",
                "symbols": out.get("symbols") or symbols,
                "advice": out.get("advice"),
                "metrics": out.get("metrics"),
                "strategy_desc": out.get("strategy_desc"),
                "audit_record": out.get("audit_record"),
            }
            return save_job_result(job_id, snap), out

        if jtype == "macro_panel":
            from quant_rd_tool.macro_panel import build_macro_panel, save_macro_panel

            self.store.mark_progress(job_id, 0.2, message="macro panel")
            panel = build_macro_panel(
                code=payload.get("code"),
                countries=tuple(payload.get("countries") or ("china", "united_states")),
                use_fred=bool(payload.get("use_fred", True)),
                fred_start_date=str(payload.get("fred_start_date", "2020-01-01")),
                use_fmp_peers=bool(payload.get("use_fmp_peers", True)),
            )
            saved = None
            out_dir = payload.get("output_dir")
            if out_dir:
                saved = save_macro_panel(panel, str(out_dir))
            snap = {
                "kind": "macro",
                "code": payload.get("code"),
                "markdown": panel.get("markdown", "")[:65536],
                "saved": saved,
                "countries": payload.get("countries"),
            }
            return save_job_result(job_id, snap), panel

        if jtype == "crypto_analyze":
            from quant_rd_tool.crypto_analysis import analyze_crypto

            sym = str(payload.get("symbol", "BTC"))
            self.store.mark_progress(job_id, 0.2, message="crypto analyze")
            out = analyze_crypto(
                sym,
                timeframe=str(payload.get("timeframe", "5m")),
                limit=int(payload.get("limit", 500)),
                data_dir=str(payload.get("data_dir", "data/crypto")),
                with_ml=bool(payload.get("with_ml", True)),
                ml_algorithm=str(payload.get("ml_algorithm", "both")),
                with_options_vol=bool(payload.get("with_options_vol", True)),
            )
            signal = out.get("combined_signal") if isinstance(out.get("combined_signal"), dict) else {}
            snap = {
                "kind": "crypto_analyze",
                "symbol": sym,
                "pair": out.get("pair"),
                "timeframe": out.get("timeframe"),
                "period": out.get("period"),
                "combined_signal": signal,
                "ui_summary": out.get("ui_summary"),
                "narrative": out.get("narrative"),
                "options_vol": out.get("options_vol"),
                "news_digest": out.get("news_digest"),
                "report_path": out.get("report_path"),
            }
            return save_job_result(job_id, snap), out

        if jtype == "crypto_workflow":
            from quant_rd_tool.crypto_workflow import resolve_template_for_run, run_workflow

            data_dir = str(payload.get("data_dir", "data/crypto"))
            tpl = resolve_template_for_run(
                data_dir=data_dir,
                template_id=payload.get("template_id"),
                template=payload.get("template"),
                timeframe=payload.get("timeframe"),
                steps=payload.get("steps"),
            )
            sym = str(payload.get("symbol") or tpl.get("symbol_default") or "BTC").strip().upper()

            def _on_progress(progress: float, message: str) -> None:
                self.store.mark_progress(job_id, progress, message=message)

            out = run_workflow(
                symbol=sym,
                template=tpl,
                data_dir=data_dir,
                refresh_ohlcv=bool(payload.get("refresh_ohlcv", True)),
                save=True,
                progress_cb=_on_progress,
            )
            advice = out.get("advice") or {}
            snap = {
                "kind": "crypto_workflow",
                "run_id": out.get("run_id"),
                "symbol": out.get("symbol"),
                "timeframe": out.get("timeframe"),
                "template_id": out.get("template_id"),
                "stance": advice.get("stance"),
                "risk_level": advice.get("risk_level"),
                "headline": advice.get("headline"),
                "data_dir": data_dir,
            }
            return save_job_result(job_id, snap), out

        if jtype == "stock_workflow":
            from quant_rd_tool.stock_workflow import resolve_template_for_run, run_workflow

            data_dir = str(payload.get("data_dir", "data/stocks"))
            tpl = resolve_template_for_run(
                data_dir=data_dir,
                template_id=payload.get("template_id"),
                template=payload.get("template"),
                timeframe=payload.get("timeframe"),
                steps=payload.get("steps"),
            )
            sym = str(payload.get("symbol") or tpl.get("symbol_default") or "600519").strip()

            def _on_progress(progress: float, message: str) -> None:
                self.store.mark_progress(job_id, progress, message=message)

            out = run_workflow(
                symbol=sym,
                template=tpl,
                data_dir=data_dir,
                refresh_ohlcv=bool(payload.get("refresh_ohlcv", True)),
                save=True,
                progress_cb=_on_progress,
            )
            advice = out.get("advice") or {}
            snap = {
                "kind": "stock_workflow",
                "run_id": out.get("run_id"),
                "symbol": out.get("symbol"),
                "code": out.get("code"),
                "timeframe": out.get("timeframe"),
                "template_id": out.get("template_id"),
                "stance": advice.get("stance"),
                "risk_level": advice.get("risk_level"),
                "headline": advice.get("headline"),
                "data_dir": data_dir,
            }
            return save_job_result(job_id, snap), out

        if jtype == "crypto_options_vol_scan":
            from quant_rd_tool.crypto_options_vol_scan import run_options_iv_maintenance

            self.store.mark_progress(job_id, 0.2, message="options iv scan")
            out = run_options_iv_maintenance(
                data_dir=str(payload.get("data_dir", self.data_dir)),
            )
            snap = {
                "kind": "crypto_options_vol_scan",
                "scanned_at": out.get("scanned_at"),
                "elevated_bases": out.get("elevated_bases"),
                "items": out.get("items"),
                "advice_overview": (out.get("advice_pack") or {}).get("overview"),
            }
            return save_job_result(job_id, snap), out

        raise ValueError(f"Unknown job type: {jtype}")
