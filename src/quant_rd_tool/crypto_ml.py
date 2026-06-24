"""Qlib ML layer for crypto: Alpha158 + XGB/LGB and combined signals."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_analyzer import CryptoStance
from quant_rd_tool.qlib_ml import MlAlgorithm, run_ml_analysis

logger = logging.getLogger(__name__)

CRYPTO_MIN_BARS = 400
ML_CACHE_DIRNAME = "ml_cache"
ML_CACHE_KEEP = 10


def _is_intraday_timeframe(timeframe: str) -> bool:
    return timeframe.strip().lower() not in ("1d", "day", "d")


def _ml_cache_path(
    qlib_dir: str,
    qlib_code: str,
    *,
    end_date: str,
    num_bars: int,
    algorithm: str,
    timeframe: str,
) -> Path:
    key = hashlib.sha256(
        f"{qlib_code}|{end_date}|{num_bars}|{algorithm}|{timeframe}".encode()
    ).hexdigest()[:24]
    return Path(qlib_dir).parent / ML_CACHE_DIRNAME / f"{key}.json"


def _load_ml_cache(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    result = cached.get("result")
    if isinstance(result, dict):
        result["cache_hit"] = True
        result["cached_at"] = cached.get("cached_at")
        return result
    return None


def _save_ml_cache(path: Path, result: dict[str, Any]) -> None:
    try:
        payload = {"cached_at": now_iso(), "result": result}
        text = json.dumps(payload, ensure_ascii=False, default=str)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        files = sorted(path.parent.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[ML_CACHE_KEEP:]:
            old.unlink(missing_ok=True)
    except Exception as e:
        logger.debug("skip ml cache write: %s", e)


def run_crypto_ml_analysis(
    qlib_dir: str,
    qlib_code: str,
    *,
    start_date: str,
    end_date: str,
    num_bars: int,
    algorithm: MlAlgorithm = "both",
    timeframe: str = "1d",
    use_cache: bool = True,
) -> dict[str, Any]:
    """Alpha158 + XGB/LGB on crypto qlib dump (same pipeline as A-shares).

    Results are cached on disk keyed by (code, end_date, num_bars, algorithm,
    timeframe): re-running analyze/workflow on unchanged data skips retraining.
    """
    intraday = _is_intraday_timeframe(timeframe)
    min_bars = 400 if not intraday else 2000
    if num_bars < min_bars:
        return {
            "enabled": False,
            "skipped": True,
            "reason": (
                f"样本不足（{num_bars} 条 K 线），qlib 训练建议至少 {min_bars} 根"
                f"（{timeframe}）。请增大 --backfill-days 或等待定时任务累积。"
            ),
        }

    cache_path = _ml_cache_path(
        qlib_dir,
        qlib_code,
        end_date=end_date,
        num_bars=num_bars,
        algorithm=algorithm,
        timeframe=timeframe,
    )
    if use_cache:
        cached = _load_ml_cache(cache_path)
        if cached is not None:
            logger.info("crypto ML cache hit for %s (%s)", qlib_code, timeframe)
            return cached

    min_span_days = 60 if intraday else 365
    qlib_freq = cxt.timeframe_to_qlib_freq(timeframe)
    result = run_ml_analysis(
        qlib_dir,
        qlib_code,
        start_date=start_date,
        end_date=end_date,
        num_bars=num_bars,
        algorithm=algorithm,
        min_span_days=min_span_days,
        intraday=intraday,
        qlib_freq=qlib_freq,
    )
    if use_cache and result.get("enabled"):
        _save_ml_cache(cache_path, result)
    return result


def ml_signal_to_stance(ml_signal: str | None) -> CryptoStance | None:
    if not ml_signal:
        return None
    if "偏多" in ml_signal:
        return "看涨"
    if "偏空" in ml_signal:
        return "看跌"
    return "中性"


def _pick_ml_latest(ml_analysis: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ml_analysis or not ml_analysis.get("enabled"):
        return None
    if ml_analysis.get("algorithm") == "both" and ml_analysis.get("models"):
        comp = ml_analysis.get("comparison") or {}
        pref = comp.get("preferred_by_ic")
        models = ml_analysis.get("models") or {}
        if pref and pref in models and models[pref].get("enabled"):
            return models[pref]
        for m in models.values():
            if m.get("enabled"):
                return m
        return None
    if ml_analysis.get("latest"):
        return ml_analysis
    return None


def _ml_quality(ml_block: dict[str, Any]) -> tuple[bool, str | None]:
    """Gate ML contribution on out-of-sample quality.

    A model with non-positive test IC or sub-coin-flip direction accuracy
    should not move the combined score.
    """
    tm = ml_block.get("test_metrics") or {}
    ic = tm.get("ic")
    acc = tm.get("direction_accuracy")
    if ic is not None and float(ic) <= 0:
        return False, f"测试集 IC={float(ic):.4f} ≤ 0"
    if acc is not None and float(acc) < 0.48:
        return False, f"测试集方向命中率 {float(acc):.0%} 低于随机"
    return True, None


def merge_crypto_signals(
    technical: dict[str, Any],
    ml_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    """Combine rule-based technical signal with qlib ML output."""
    tech_stance: CryptoStance = technical["stance"]
    tech_action = technical["action"]
    score = int(technical.get("score", 0))

    ml_block = _pick_ml_latest(ml_analysis)
    ml_stance: CryptoStance | None = None
    ml_signal: str | None = None
    ml_pred: float | None = None
    ml_reliable = True
    ml_quality_note: str | None = None
    if ml_block:
        latest = ml_block.get("latest") or {}
        ml_signal = latest.get("signal")
        ml_pred = latest.get("predicted_return")
        ml_stance = ml_signal_to_stance(ml_signal)
        ml_reliable, ml_quality_note = _ml_quality(ml_block)
        if ml_reliable:
            if ml_stance == "看涨":
                score += 1
            elif ml_stance == "看跌":
                score -= 1

    if score >= 2:
        combined_stance: CryptoStance = "看涨"
        combined_action = "buy"
    elif score <= -2:
        combined_stance = "看跌"
        combined_action = "sell"
    else:
        combined_stance = "中性"
        combined_action = "hold"

    reasons = list(technical.get("reasons") or [])
    if ml_signal:
        reasons.append(f"qlib ML：{ml_signal}")
        if ml_pred is not None:
            reasons.append(f"ML 预测收益代理：{ml_pred:.4f}")
        if not ml_reliable and ml_quality_note:
            reasons.append(f"ML 质量门控：{ml_quality_note}，不计入综合评分")

    agreement = "一致" if ml_stance == tech_stance else ("分歧" if ml_stance else "仅技术面")

    return {
        "stance": combined_stance,
        "action": combined_action,
        "score": score,
        "confidence": min(abs(score) / 5.0, 1.0),
        "technical": {"stance": tech_stance, "action": tech_action},
        "ml": {
            "stance": ml_stance,
            "signal": ml_signal,
            "predicted_return": ml_pred,
            "reliable": ml_reliable if ml_block else None,
            "quality_note": ml_quality_note,
        },
        "agreement": agreement,
        "reasons": reasons,
    }


def ml_markdown_lines(ml: dict[str, Any]) -> list[str]:
    """Markdown lines for qlib ML section (crypto report)."""
    lines: list[str] = []
    if ml and (ml.get("enabled") or ml.get("models")):
        if ml.get("algorithm") == "both" and ml.get("models"):
            comp = ml.get("comparison") or {}
            if comp.get("summary"):
                lines.append(comp["summary"])
                lines.append("")
            for algo, m in (ml.get("models") or {}).items():
                if not m.get("enabled"):
                    continue
                lines.extend(_one_model_lines(m, title=f"### {algo.upper()}"))
        else:
            lines.extend(_one_model_lines(ml))
    elif ml and ml.get("skipped"):
        lines.append(f"_{ml.get('reason', '已跳过')}_")
    return lines


def _one_model_lines(ml: dict[str, Any], *, title: str = "") -> list[str]:
    lines: list[str] = []
    if title:
        lines.append(title)
    interp = ml.get("interpretation") or {}
    if interp.get("summary"):
        lines.append(interp["summary"])
    lines.append(f"- **模型信号**：{ml.get('latest', {}).get('signal', 'N/A')}")
    tm = ml.get("test_metrics") or {}
    if tm.get("ic") is not None:
        lines.append(f"- 测试集 IC：{tm['ic']:.4f}")
    if tm.get("direction_accuracy") is not None:
        lines.append(f"- 测试集方向命中率：{tm['direction_accuracy']:.2%}")
    latest = ml.get("latest") or {}
    if latest.get("predicted_return") is not None:
        lines.append(f"- 最新预测收益（标签代理）：{latest['predicted_return']:.4f}")
    lines.append("")
    lines.append("**重要因子（Top 5）**")
    for row in (ml.get("top_features") or [])[:5]:
        lines.append(f"- {row['feature']}: {row['importance']}")
    for c in interp.get("caveats") or []:
        lines.append(f"- _{c}_")
    lines.append("")
    return lines
