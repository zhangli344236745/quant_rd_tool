"""Project scan and user upload ingest for knowledge base."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool import kb_chunking, kb_embed, kb_store
from quant_rd_tool.config import project_root, settings


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_sync_state(data_dir: str | Path | None = None) -> dict[str, Any]:
    path = kb_store.sync_state_path(data_dir)
    if not path.exists():
        return {"fingerprints": {}, "last_sync_at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("fingerprints", {})
            return data
    except Exception:
        pass
    return {"fingerprints": {}, "last_sync_at": None}


def _save_sync_state(state: dict[str, Any], data_dir: str | Path | None = None) -> None:
    path = kb_store.sync_state_path(data_dir)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_pdf_text(raw: bytes) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        import io

        reader = PdfReader(io.BytesIO(raw))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
        return text or None
    except Exception:
        return None


def _ingest_text_document(
    *,
    title: str,
    text: str,
    source: str,
    path: str | None,
    mime: str | None,
    tags: list[str],
    fingerprint_key: str,
    sync_state: dict[str, Any],
    data_dir: str | Path | None = None,
    embed_fn: Any = None,
) -> dict[str, Any]:
    h = content_hash(text)
    if sync_state["fingerprints"].get(fingerprint_key) == h:
        return {"skipped": True, "path": path, "reason": "unchanged"}
    chunks_text = kb_chunking.split_text(text)
    if not chunks_text:
        return {"skipped": True, "path": path, "reason": "empty"}
    embeddings = kb_embed.embed_texts(chunks_text, embed_fn=embed_fn)
    doc_id = sync_state["fingerprints"].get(f"{fingerprint_key}:doc_id") or str(uuid.uuid4())
    kb_store.upsert_document(
        doc_id=doc_id,
        title=title,
        source=source,
        path=path,
        mime=mime,
        tags=tags,
        content_hash=h,
        data_dir=data_dir,
    )
    chunk_rows = [
        {"text": t, "embedding": e, "meta": {"ord": i}}
        for i, (t, e) in enumerate(zip(chunks_text, embeddings, strict=True))
    ]
    kb_store.replace_chunks(doc_id, chunk_rows, data_dir=data_dir)
    sync_state["fingerprints"][fingerprint_key] = h
    sync_state["fingerprints"][f"{fingerprint_key}:doc_id"] = doc_id
    return {"skipped": False, "path": path, "doc_id": doc_id, "chunks": len(chunk_rows)}


def _ingest_json_sections(
    *,
    title: str,
    data: dict[str, Any],
    source: str,
    path: str,
    tags: list[str],
    fingerprint_key: str,
    sync_state: dict[str, Any],
    data_dir: str | Path | None = None,
    embed_fn: Any = None,
) -> dict[str, Any]:
    sections = kb_chunking.split_json_report(data)
    text = "\n\n".join(sections)
    return _ingest_text_document(
        title=title,
        text=text,
        source=source,
        path=path,
        mime="application/json",
        tags=tags,
        fingerprint_key=fingerprint_key,
        sync_state=sync_state,
        data_dir=data_dir,
        embed_fn=embed_fn,
    )


def export_tv_catalog_markdown() -> str:
    from quant_rd_tool.crypto_zipline_strategies.tv_catalog import (
        list_ml_strategies,
        list_tv_strategies,
    )

    lines = ["# Zipline TV / ML 策略目录", ""]
    for spec in list_tv_strategies():
        lines.append(f"## {spec.get('name')} ({spec.get('id')})")
        lines.append(f"- 分类: {spec.get('category')}")
        lines.append(f"- 描述: {spec.get('description')}")
        lines.append(f"- TV 参考: {spec.get('tv_ref')}")
        lines.append("")
    lines.append("# ML 策略")
    lines.append("")
    for spec in list_ml_strategies():
        lines.append(f"## {spec.get('name')} ({spec.get('id')})")
        lines.append(f"- 描述: {spec.get('description')}")
        lines.append("")
    return "\n".join(lines)


def scan_project(
    *,
    data_dir: str | Path = "data",
    docs_dir: str | Path = "docs",
    kb_data_dir: str | Path | None = None,
    embed_fn: Any = None,
) -> dict[str, Any]:
    kb_store.init_db(kb_data_dir)
    root = project_root()
    data_root = root / data_dir
    docs_root = root / docs_dir
    sync_state = _load_sync_state(kb_data_dir)
    results: list[dict[str, Any]] = []

    # A-share reports
    stocks_root = data_root / "stocks"
    if stocks_root.is_dir():
        for sym_dir in sorted(stocks_root.iterdir()):
            if not sym_dir.is_dir():
                continue
            code = sym_dir.name
            for fname, mime in (("report.md", "text/markdown"), ("report.json", "application/json")):
                fpath = sym_dir / fname
                if not fpath.is_file():
                    continue
                rel = str(fpath.relative_to(root))
                key = f"project:{rel}"
                tags = ["astock", code.lower()]
                if fname.endswith(".md"):
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                    results.append(
                        _ingest_text_document(
                            title=f"A股报告 {code}",
                            text=text,
                            source="project",
                            path=rel,
                            mime=mime,
                            tags=tags,
                            fingerprint_key=key,
                            sync_state=sync_state,
                            data_dir=kb_data_dir,
                            embed_fn=embed_fn,
                        )
                    )
                else:
                    try:
                        data = json.loads(fpath.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if isinstance(data, dict):
                        results.append(
                            _ingest_json_sections(
                                title=f"A股报告 JSON {code}",
                                data=data,
                                source="project",
                                path=rel,
                                tags=tags,
                                fingerprint_key=key,
                                sync_state=sync_state,
                                data_dir=kb_data_dir,
                                embed_fn=embed_fn,
                            )
                        )

    # Crypto reports
    crypto_root = data_root / "crypto"
    if crypto_root.is_dir():
        for sym_dir in sorted(crypto_root.iterdir()):
            if not sym_dir.is_dir() or not sym_dir.name.startswith("CRYPTO_"):
                continue
            symbol = sym_dir.name.replace("CRYPTO_", "")
            for fname, mime in (("report.md", "text/markdown"), ("report.json", "application/json")):
                fpath = sym_dir / fname
                if not fpath.is_file():
                    continue
                rel = str(fpath.relative_to(root))
                key = f"project:{rel}"
                tags = ["crypto", symbol.lower()]
                if fname.endswith(".md"):
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                    results.append(
                        _ingest_text_document(
                            title=f"Crypto 报告 {symbol}",
                            text=text,
                            source="project",
                            path=rel,
                            mime=mime,
                            tags=tags,
                            fingerprint_key=key,
                            sync_state=sync_state,
                            data_dir=kb_data_dir,
                            embed_fn=embed_fn,
                        )
                    )
                else:
                    try:
                        data = json.loads(fpath.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if isinstance(data, dict):
                        results.append(
                            _ingest_json_sections(
                                title=f"Crypto 报告 JSON {symbol}",
                                data=data,
                                source="project",
                                path=rel,
                                tags=tags,
                                fingerprint_key=key,
                                sync_state=sync_state,
                                data_dir=kb_data_dir,
                                embed_fn=embed_fn,
                            )
                        )

    # News digests
    news_dir = crypto_root / "news"
    if news_dir.is_dir():
        for fpath in sorted(news_dir.glob("digest*.json")):
            rel = str(fpath.relative_to(root))
            key = f"project:{rel}"
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict):
                results.append(
                    _ingest_json_sections(
                        title=f"Crypto 新闻 Digest {fpath.name}",
                        data=data,
                        source="project",
                        path=rel,
                        tags=["news", "crypto"],
                        fingerprint_key=key,
                        sync_state=sync_state,
                        data_dir=kb_data_dir,
                        embed_fn=embed_fn,
                    )
                )

    # Design specs
    specs_dir = docs_root / "superpowers" / "specs"
    if specs_dir.is_dir():
        for fpath in sorted(specs_dir.glob("*-design.md")):
            rel = str(fpath.relative_to(root))
            key = f"project:{rel}"
            text = fpath.read_text(encoding="utf-8", errors="replace")
            results.append(
                _ingest_text_document(
                    title=f"设计文档 {fpath.stem}",
                    text=text,
                    source="project",
                    path=rel,
                    mime="text/markdown",
                    tags=["docs", "strategy"],
                    fingerprint_key=key,
                    sync_state=sync_state,
                    data_dir=kb_data_dir,
                    embed_fn=embed_fn,
                )
            )

    # TV catalog synthetic doc
    tv_md = export_tv_catalog_markdown()
    tv_key = "project:tv_catalog"
    results.append(
        _ingest_text_document(
            title="Zipline TV/ML 策略目录",
            text=tv_md,
            source="project",
            path="crypto_zipline_strategies/tv_catalog",
            mime="text/markdown",
            tags=["strategy", "zipline"],
            fingerprint_key=tv_key,
            sync_state=sync_state,
            data_dir=kb_data_dir,
            embed_fn=embed_fn,
        )
    )

    sync_state["last_sync_at"] = now_iso()
    _save_sync_state(sync_state, kb_data_dir)
    ingested = sum(1 for r in results if not r.get("skipped"))
    skipped = sum(1 for r in results if r.get("skipped"))
    return {
        "ingested": ingested,
        "skipped": skipped,
        "total_scanned": len(results),
        "last_sync_at": sync_state["last_sync_at"],
        "items": results,
    }


def ingest_upload(
    file_bytes: bytes,
    filename: str,
    *,
    mime: str | None = None,
    kb_data_dir: str | Path | None = None,
    embed_fn: Any = None,
) -> dict[str, Any]:
    kb_store.init_db(kb_data_dir)
    name = Path(filename).name
    suffix = Path(name).suffix.lower()
    allowed = {".md", ".txt", ".pdf"}
    if suffix not in allowed:
        raise ValueError(f"unsupported file type: {suffix}")
    if len(file_bytes) > 10 * 1024 * 1024:
        raise ValueError("file exceeds 10MB limit")

    uploads_dir = kb_store.kb_root(kb_data_dir) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{name}"
    stored_path = uploads_dir / stored_name
    stored_path.write_bytes(file_bytes)

    text: str | None = None
    detected_mime = mime
    if suffix in {".md", ".txt"}:
        text = file_bytes.decode("utf-8", errors="replace")
        detected_mime = "text/markdown" if suffix == ".md" else "text/plain"
    elif suffix == ".pdf":
        text = _extract_pdf_text(file_bytes)
        detected_mime = "application/pdf"
        if text is None:
            return {
                "ok": False,
                "warning": "PDF text extraction unavailable (install pypdf)",
                "path": str(stored_path),
            }

    if not text or not text.strip():
        return {"ok": False, "warning": "empty document", "path": str(stored_path)}

    sync_state = _load_sync_state(kb_data_dir)
    key = f"upload:{stored_name}"
    rel_path = str(stored_path.relative_to(project_root()))
    result = _ingest_text_document(
        title=name,
        text=text,
        source="upload",
        path=rel_path,
        mime=detected_mime,
        tags=["upload"],
        fingerprint_key=key,
        sync_state=sync_state,
        data_dir=kb_data_dir,
        embed_fn=embed_fn,
    )
    _save_sync_state(sync_state, kb_data_dir)
    return {"ok": True, **result, "filename": name}
