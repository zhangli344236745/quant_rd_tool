"""Scan local stock report artifacts under data/stocks/."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool import akshare_data as ak_data
from quant_rd_tool.stock_storage import report_json_path, report_md_path, stock_root


def _load_report_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_report_summary(path: Path) -> dict[str, Any]:
    data = _load_report_json(path)
    narrative = data.get("narrative") or {}
    if not isinstance(narrative, dict):
        narrative = {}
    return {
        "symbol": data.get("symbol"),
        "stance": narrative.get("stance"),
        "summary": narrative.get("summary"),
        "generated_at": data.get("generated_at"),
    }


def _ml_compact(ml: Any) -> dict[str, Any] | None:
    if not isinstance(ml, dict):
        return None
    out: dict[str, Any] = {}
    if ml.get("skipped"):
        out["skipped"] = True
        out["reason"] = ml.get("reason") or ml.get("skip_reason")
        return out
    comparison = ml.get("comparison")
    if isinstance(comparison, dict):
        out["comparison"] = comparison
    models = ml.get("models")
    if isinstance(models, dict):
        out["models"] = {
            k: {
                "signal": (v or {}).get("signal"),
                "predicted_return": (v or {}).get("predicted_return"),
            }
            for k, v in models.items()
            if isinstance(v, dict)
        }
    return out or None


def _report_compare_slice(path: Path, *, bare_code: str, qlib_code: str) -> dict[str, Any]:
    data = _load_report_json(path)
    narrative = data.get("narrative") or {}
    analysis = data.get("analysis") or {}
    openbb = data.get("openbb") if isinstance(data.get("openbb"), dict) else {}
    macro = openbb.get("macro") if isinstance(openbb.get("macro"), dict) else {}
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    return {
        "code": bare_code,
        "qlib_code": qlib_code,
        "stance": narrative.get("stance") if isinstance(narrative, dict) else None,
        "summary": narrative.get("summary") if isinstance(narrative, dict) else None,
        "report_mtime": mtime,
        "technical": analysis.get("technical") if isinstance(analysis, dict) else None,
        "returns": analysis.get("returns") if isinstance(analysis, dict) else None,
        "price": analysis.get("price") if isinstance(analysis, dict) else None,
        "risk": analysis.get("risk") if isinstance(analysis, dict) else None,
        "ml": _ml_compact(data.get("ml_analysis")),
        "macro_summary": macro.get("summary") if macro.get("available") else None,
    }


def _resolve_report_path(code: str, *, data_dir: str | Path) -> tuple[Path, str, str]:
    root = stock_root(data_dir, code)
    rjson = report_json_path(root)
    if not rjson.is_file():
        raise FileNotFoundError(f"No report for {code}")
    qlib_code = root.name
    bare = ak_data.to_ak_code(qlib_code)
    return rjson, bare, qlib_code


def compare_reports(
    code_a: str,
    code_b: str,
    *,
    data_dir: str | Path = "data/stocks",
) -> dict[str, Any]:
    path_a, bare_a, qlib_a = _resolve_report_path(code_a, data_dir=data_dir)
    path_b, bare_b, qlib_b = _resolve_report_path(code_b, data_dir=data_dir)
    return {
        "a": _report_compare_slice(path_a, bare_code=bare_a, qlib_code=qlib_a),
        "b": _report_compare_slice(path_b, bare_code=bare_b, qlib_code=qlib_b),
    }


def list_reports(
    *,
    data_dir: str | Path = "data/stocks",
    q: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    base = Path(data_dir).expanduser()
    if not base.is_dir():
        return {"total": 0, "page": page, "page_size": page_size, "items": []}

    rows: list[dict[str, Any]] = []
    q_norm = (q or "").strip().lower()
    for child in base.iterdir():
        if not child.is_dir():
            continue
        rpath = child / "report.json"
        if not rpath.is_file():
            continue
        summary = _read_report_summary(rpath)
        qlib_code = child.name
        bare = ak_data.to_ak_code(qlib_code)
        if q_norm and q_norm not in qlib_code.lower() and q_norm not in bare.lower():
            continue
        mtime = datetime.fromtimestamp(rpath.stat().st_mtime, tz=UTC).isoformat()
        rows.append(
            {
                "qlib_code": qlib_code,
                "code": bare,
                "stance": summary.get("stance"),
                "summary": summary.get("summary"),
                "report_mtime": mtime,
                "report_path": str(rpath),
            }
        )

    rows.sort(key=lambda x: x.get("report_mtime") or "", reverse=True)
    total = len(rows)
    start = (max(1, page) - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": rows[start:end],
    }


def latest_report(code: str, *, data_dir: str | Path = "data/stocks") -> dict[str, Any]:
    rjson, bare, qlib_code = _resolve_report_path(code, data_dir=data_dir)
    summary = _read_report_summary(rjson)
    data = _load_report_json(rjson)
    openbb = data.get("openbb") if isinstance(data.get("openbb"), dict) else {}
    macro = openbb.get("macro") if isinstance(openbb.get("macro"), dict) else None
    macro_out = None
    if isinstance(macro, dict) and macro.get("available"):
        macro_out = {
            "summary": macro.get("summary"),
            "china": macro.get("china"),
            "global": macro.get("global"),
        }

    md_path = report_md_path(stock_root(data_dir, code))
    markdown = ""
    if md_path.is_file():
        text = md_path.read_text(encoding="utf-8")
        markdown = text[:65536]

    mtime = datetime.fromtimestamp(rjson.stat().st_mtime, tz=UTC).isoformat()
    from quant_rd_tool.report_versions import verify_report_version

    verify = verify_report_version(bare, "latest", data_dir=data_dir)
    compliance = data.get("_compliance") if isinstance(data.get("_compliance"), dict) else None
    return {
        "code": bare,
        "qlib_code": qlib_code,
        "stance": summary.get("stance"),
        "summary": summary.get("summary"),
        "symbol": summary.get("symbol"),
        "report_mtime": mtime,
        "report_path": str(rjson.resolve()),
        "markdown": markdown,
        "macro": macro_out,
        "technical": (data.get("analysis") or {}).get("technical")
        if isinstance(data.get("analysis"), dict)
        else None,
        "ml": _ml_compact(data.get("ml_analysis")),
        "compliance": {
            **(compliance or {}),
            "integrity": verify,
        },
    }


def build_reports_zip(
    *,
    data_dir: str | Path = "data/stocks",
    codes: list[str] | None = None,
    watermark: bool = True,
) -> bytes:
    """Zip report.json + report.md per symbol (read-only share bundle)."""
    from quant_rd_tool.research_audit import (
        build_export_manifest,
        verify_audit_chain,
        watermark_markdown,
    )
    from quant_rd_tool.report_versions import verify_report_version

    listed = list_reports(data_dir=data_dir, page=1, page_size=10_000)
    code_set = {c.strip() for c in (codes or []) if c.strip()}
    manifest_items: list[dict[str, Any]] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in listed["items"]:
            if code_set and row["code"] not in code_set and row["qlib_code"] not in code_set:
                continue
            root = stock_root(data_dir, row["code"])
            rjson = report_json_path(root)
            rmd = report_md_path(root)
            prefix = row["qlib_code"]
            verify = verify_report_version(row["code"], "latest", data_dir=data_dir)
            manifest_items.append(
                {
                    "code": row["code"],
                    "qlib_code": row["qlib_code"],
                    "version_id": "latest",
                    "content_hash": verify.get("content_hash"),
                    "locked": verify.get("locked"),
                }
            )
            if rjson.is_file():
                zf.writestr(f"{prefix}/report.json", rjson.read_bytes())
            if rmd.is_file():
                md_text = rmd.read_text(encoding="utf-8")
                if watermark:
                    md_text = watermark_markdown(
                        md_text,
                        meta={
                            "content_hash": verify.get("content_hash"),
                            "exported_at": now_iso(),
                        },
                    )
                zf.writestr(f"{prefix}/report.md", md_text.encode("utf-8"))
        if watermark and manifest_items:
            zf.writestr(
                "compliance/manifest.json",
                json.dumps(
                    build_export_manifest(
                        items=manifest_items,
                        chain_verify=verify_audit_chain(data_dir=data_dir),
                    ),
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8"),
            )
        if not zf.namelist():
            raise FileNotFoundError("No reports to export")
    return buf.getvalue()


def report_history(code: str, *, data_dir: str | Path = "data/stocks") -> list[dict[str, Any]]:
    from quant_rd_tool.report_versions import list_report_versions

    return list_report_versions(code, data_dir=data_dir)


def diff_report_versions(
    code: str,
    *,
    data_dir: str | Path = "data/stocks",
    base_version: str | None = None,
    compare_version: str = "latest",
) -> dict[str, Any]:
    from quant_rd_tool.report_versions import diff_report_versions as _diff

    return _diff(
        code,
        data_dir=data_dir,
        base_version=base_version,
        compare_version=compare_version,
    )
