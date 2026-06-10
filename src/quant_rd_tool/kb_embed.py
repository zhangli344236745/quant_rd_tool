"""Embedding helpers for knowledge base vector search."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Callable

from quant_rd_tool.config import settings

_KEYWORD_DIM = 256
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if len(t) > 1]


def embed_texts_keyword_fallback(texts: list[str]) -> list[list[float]]:
    """Deterministic hash embedding when OpenAI key is unavailable."""
    out: list[list[float]] = []
    for text in texts:
        vec = [0.0] * _KEYWORD_DIM
        tokens = _tokenize(text)
        if not tokens:
            out.append(vec)
            continue
        for tok in tokens:
            h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
            idx = h % _KEYWORD_DIM
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out


def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    api_key: str | None = None,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    if embed_fn is not None:
        return embed_fn(texts)
    key = api_key or settings.openai_api_key
    if not key:
        return embed_texts_keyword_fallback(texts)
    try:
        from openai import OpenAI
    except ImportError:
        return embed_texts_keyword_fallback(texts)

    client = OpenAI(api_key=key, base_url=settings.openai_api_base)
    model_name = model or settings.kb_embedding_model
    resp = client.embeddings.create(model=model_name, input=texts)
    ordered = sorted(resp.data, key=lambda x: x.index)
    return [list(item.embedding) for item in ordered]
