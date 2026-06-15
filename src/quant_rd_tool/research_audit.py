"""Compliance audit chain for A-share research runs (hash-linked JSONL)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64

DEFAULT_DISCLAIMER = (
    "本报告由 quant-rd-tool 自动生成，仅供内部研究参考，不构成任何投资建议。"
    "历史回测与模型输出不代表未来表现。"
)

DEFAULT_WATERMARK = "【研究用途 · 非投资建议 · quant-rd-tool】"


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hash_payload(payload: dict[str, Any]) -> str:
    return sha256_hex(_canonical_json(payload))


def compliance_root(data_dir: str | Path = "data/stocks") -> Path:
    root = Path(data_dir) / "compliance"
    root.mkdir(parents=True, exist_ok=True)
    return root


def audit_chain_path(data_dir: str | Path = "data/stocks") -> Path:
    return compliance_root(data_dir) / "audit_chain.jsonl"


def report_locks_path(data_dir: str | Path = "data/stocks") -> Path:
    return compliance_root(data_dir) / "report_locks.json"


def _read_chain_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _last_entry_hash(path: Path) -> str:
    rows = _read_chain_lines(path)
    if not rows:
        return GENESIS_HASH
    return str(rows[-1].get("entry_hash") or GENESIS_HASH)


def record_research_run(
    run_type: str,
    *,
    inputs: dict[str, Any],
    outputs_summary: dict[str, Any],
    code: str | None = None,
    data_dir: str | Path = "data/stocks",
    run_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Append a hash-linked audit entry; returns compliance metadata for API responses."""
    path = audit_chain_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    run_id = run_id or str(uuid.uuid4())
    ts = datetime.now(UTC).isoformat()
    prev_hash = _last_entry_hash(path)
    body = {
        "run_id": run_id,
        "run_type": run_type,
        "code": code,
        "job_id": job_id,
        "ts": ts,
        "inputs": inputs,
        "outputs_summary": outputs_summary,
    }
    content_hash = hash_payload(body)
    entry_hash = sha256_hex(f"{prev_hash}:{content_hash}")
    entry = {
        **body,
        "prev_hash": prev_hash,
        "content_hash": content_hash,
        "entry_hash": entry_hash,
        "disclaimer": DEFAULT_DISCLAIMER,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    return {
        "run_id": run_id,
        "run_type": run_type,
        "ts": ts,
        "content_hash": content_hash,
        "entry_hash": entry_hash,
        "prev_hash": prev_hash,
        "disclaimer": DEFAULT_DISCLAIMER,
    }


def tail_research_audit(
    *,
    limit: int = 50,
    run_type: str | None = None,
    code: str | None = None,
    data_dir: str | Path = "data/stocks",
) -> list[dict[str, Any]]:
    rows = _read_chain_lines(audit_chain_path(data_dir))
    out: list[dict[str, Any]] = []
    for row in reversed(rows):
        if run_type and row.get("run_type") != run_type:
            continue
        if code and row.get("code") != code:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    out.reverse()
    return out


def get_audit_entry(run_id: str, *, data_dir: str | Path = "data/stocks") -> dict[str, Any] | None:
    for row in _read_chain_lines(audit_chain_path(data_dir)):
        if row.get("run_id") == run_id:
            return row
    return None


def verify_audit_chain(*, data_dir: str | Path = "data/stocks") -> dict[str, Any]:
    rows = _read_chain_lines(audit_chain_path(data_dir))
    if not rows:
        return {"valid": True, "entries": 0, "message": "empty chain"}

    prev = GENESIS_HASH
    errors: list[str] = []
    for i, row in enumerate(rows):
        if row.get("prev_hash") != prev:
            errors.append(f"entry {i}: prev_hash mismatch")
        body = {
            k: row[k]
            for k in ("run_id", "run_type", "code", "job_id", "ts", "inputs", "outputs_summary")
            if k in row
        }
        expected_content = hash_payload(body)
        if row.get("content_hash") != expected_content:
            errors.append(f"entry {i}: content_hash mismatch")
        expected_entry = sha256_hex(f"{prev}:{expected_content}")
        if row.get("entry_hash") != expected_entry:
            errors.append(f"entry {i}: entry_hash mismatch")
        prev = str(row.get("entry_hash") or GENESIS_HASH)

    return {
        "valid": not errors,
        "entries": len(rows),
        "head_hash": rows[-1].get("entry_hash"),
        "errors": errors[:20],
    }


def _load_report_locks(data_dir: str | Path) -> dict[str, Any]:
    path = report_locks_path(data_dir)
    if not path.is_file():
        return {"locks": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"locks": {}}


def _save_report_locks(data_dir: str | Path, data: dict[str, Any]) -> None:
    path = report_locks_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def lock_report_version(
    code: str,
    version_id: str,
    *,
    locked_by: str = "user",
    reason: str = "",
    data_dir: str | Path = "data/stocks",
) -> dict[str, Any]:
    from quant_rd_tool.report_versions import verify_report_version

    verify = verify_report_version(code, version_id, data_dir=data_dir)
    if not verify.get("valid"):
        raise ValueError(verify.get("message") or "report integrity check failed")

    store = _load_report_locks(data_dir)
    locks: dict[str, Any] = store.setdefault("locks", {})
    key = f"{code.strip()}:{version_id}"
    if key in locks:
        return locks[key]
    row = {
        "code": code.strip(),
        "version_id": version_id,
        "locked_at": datetime.now(UTC).isoformat(),
        "locked_by": locked_by,
        "reason": reason,
        "content_hash": verify.get("content_hash"),
    }
    locks[key] = row
    _save_report_locks(data_dir, store)
    return row


def list_report_locks(*, code: str | None = None, data_dir: str | Path = "data/stocks") -> list[dict[str, Any]]:
    locks = _load_report_locks(data_dir).get("locks") or {}
    rows = list(locks.values())
    if code:
        bare = code.strip()
        rows = [r for r in rows if r.get("code") == bare]
    return sorted(rows, key=lambda r: r.get("locked_at") or "", reverse=True)


def is_report_locked(code: str, version_id: str, *, data_dir: str | Path = "data/stocks") -> bool:
    key = f"{code.strip()}:{version_id}"
    return key in (_load_report_locks(data_dir).get("locks") or {})


def watermark_markdown(text: str, *, meta: dict[str, Any] | None = None) -> str:
    meta = meta or {}
    lines = [
        DEFAULT_WATERMARK,
        f"导出时间: {meta.get('exported_at', datetime.now(UTC).isoformat())}",
    ]
    if meta.get("content_hash"):
        lines.append(f"内容哈希: {meta['content_hash']}")
    if meta.get("run_id"):
        lines.append(f"审计 run_id: {meta['run_id']}")
    lines.append(DEFAULT_DISCLAIMER)
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + text


def build_export_manifest(
    *,
    items: list[dict[str, Any]],
    chain_verify: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "disclaimer": DEFAULT_DISCLAIMER,
        "watermark": DEFAULT_WATERMARK,
        "reports": items,
        "audit_chain": chain_verify or verify_audit_chain(),
    }
