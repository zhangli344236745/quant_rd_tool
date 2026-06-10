"""Text chunking helpers for knowledge base ingest."""

from __future__ import annotations

import json
from typing import Any


def split_text(
    text: str,
    *,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start += step
    return chunks


def split_json_report(data: dict[str, Any]) -> list[str]:
    """Split JSON report by top-level keys into readable sections."""
    if not data:
        return []
    sections: list[str] = []
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            body = json.dumps(value, ensure_ascii=False, indent=2)
        else:
            body = str(value)
        body = body.strip()
        if not body:
            continue
        sections.append(f"## {key}\n{body}")
    return sections
