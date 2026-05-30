"""Archive and diff stock report.json versions under {root}/reports/."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool.stock_storage import report_json_path, report_md_path, stock_root


def _version_id_from_path(path: Path) -> str:
    return path.stem


def reports_dir(root: Path) -> Path:
    d = root / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def archive_report_if_exists(root: Path) -> str | None:
    """Copy current report.json/md into reports/{ts}.json before overwrite."""
    rjson = report_json_path(root)
    if not rjson.is_file():
        return None
    mtime = datetime.fromtimestamp(rjson.stat().st_mtime, tz=UTC)
    vid = mtime.strftime("%Y%m%dT%H%M%SZ")
    dest = reports_dir(root) / f"{vid}.json"
    if dest.exists():
        vid = f"{vid}_{int(mtime.microsecond / 1000):03d}"
        dest = reports_dir(root) / f"{vid}.json"
    shutil.copy2(rjson, dest)
    rmd = report_md_path(root)
    if rmd.is_file():
        shutil.copy2(rmd, reports_dir(root) / f"{vid}.md")
    try:
        old = json.loads(rjson.read_text(encoding="utf-8"))
        stance = (old.get("narrative") or {}).get("stance")
    except Exception:
        stance = None
    meta_path = reports_dir(root) / f"{vid}.meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "version_id": vid,
                "archived_at": datetime.now(UTC).isoformat(),
                "source_mtime": mtime.isoformat(),
                "stance": stance,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return vid


def list_report_versions(code: str, *, data_dir: str | Path = "data/stocks") -> list[dict[str, Any]]:
    root = stock_root(data_dir, code)
    rdir = root / "reports"
    rows: list[dict[str, Any]] = []
    latest_json = report_json_path(root)
    if latest_json.is_file():
        summary = _read_summary(latest_json)
        rows.append(
            {
                "version_id": "latest",
                "report_mtime": datetime.fromtimestamp(latest_json.stat().st_mtime, tz=UTC).isoformat(),
                "is_latest": True,
                **summary,
            }
        )
    if rdir.is_dir():
        for p in sorted(rdir.glob("*.json"), reverse=True):
            if p.name.endswith(".meta.json"):
                continue
            vid = _version_id_from_path(p)
            summary = _read_summary(p)
            rows.append(
                {
                    "version_id": vid,
                    "report_mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=UTC).isoformat(),
                    "is_latest": False,
                    **summary,
                }
            )
    return rows


def _read_summary(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    narrative = data.get("narrative") or {}
    return {
        "stance": narrative.get("stance") if isinstance(narrative, dict) else None,
        "summary": narrative.get("summary") if isinstance(narrative, dict) else None,
        "generated_at": data.get("generated_at"),
    }


def load_report_version(
    code: str,
    version_id: str,
    *,
    data_dir: str | Path = "data/stocks",
) -> dict[str, Any]:
    root = stock_root(data_dir, code)
    if version_id == "latest":
        path = report_json_path(root)
    else:
        path = reports_dir(root) / f"{version_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Version not found: {version_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def diff_report_versions(
    code: str,
    *,
    data_dir: str | Path = "data/stocks",
    base_version: str | None = None,
    compare_version: str = "latest",
) -> dict[str, Any]:
    versions = list_report_versions(code, data_dir=data_dir)
    archived = [v for v in versions if not v.get("is_latest")]
    if not archived and compare_version == "latest":
        raise FileNotFoundError("No previous version to compare")

    if base_version is None:
        non_latest = [v for v in versions if not v.get("is_latest")]
        if not non_latest:
            raise FileNotFoundError("No previous version to compare")
        base_version = non_latest[0]["version_id"]

    old = load_report_version(code, base_version, data_dir=data_dir)
    new = load_report_version(code, compare_version, data_dir=data_dir)
    changes = _build_changes(old, new)
    summary = _summarize_changes(changes)
    return {
        "code": code,
        "base_version": base_version,
        "compare_version": compare_version,
        "changes": changes,
        "summary": summary,
        "base_stance": (old.get("narrative") or {}).get("stance"),
        "compare_stance": (new.get("narrative") or {}).get("stance"),
    }


def _build_changes(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    on = old.get("narrative") or {}
    nn = new.get("narrative") or {}
    if on.get("stance") != nn.get("stance"):
        changes.append({"field": "stance", "from": on.get("stance"), "to": nn.get("stance")})
    if on.get("summary") != nn.get("summary"):
        changes.append({"field": "summary", "from": on.get("summary"), "to": nn.get("summary")})

    oa = old.get("analysis") or {}
    na = new.get("analysis") or {}
    ot = oa.get("technical") or {}
    nt = na.get("technical") or {}
    for key in ("ma_alignment", "rsi_14", "rsi_zone"):
        if ot.get(key) != nt.get(key):
            changes.append({"field": f"technical.{key}", "from": ot.get(key), "to": nt.get(key)})

    ore = oa.get("returns") or {}
    nre = na.get("returns") or {}
    for key in ("1d", "5d", "20d", "60d"):
        if ore.get(key) != nre.get(key):
            changes.append(
                {
                    "field": f"returns.{key}",
                    "from": ore.get(key),
                    "to": nre.get(key),
                }
            )

    oml = old.get("ml_analysis") or {}
    nml = new.get("ml_analysis") or {}
    if isinstance(oml, dict) and isinstance(nml, dict):
        for model in set(oml.get("models") or {}) | set(nml.get("models") or {}):
            osig = ((oml.get("models") or {}).get(model) or {}).get("signal")
            nsig = ((nml.get("models") or {}).get(model) or {}).get("signal")
            if osig != nsig:
                changes.append(
                    {
                        "field": f"ml.{model}.signal",
                        "from": osig,
                        "to": nsig,
                    }
                )
    return changes


def _summarize_changes(changes: list[dict[str, Any]]) -> str:
    if not changes:
        return "与上一版相比无显著字段变化。"
    parts: list[str] = []
    for c in changes[:8]:
        parts.append(f"{c['field']}: {c.get('from')} → {c.get('to')}")
    if len(changes) > 8:
        parts.append(f"…共 {len(changes)} 项变化")
    return "；".join(parts)
