"""Lightweight qlib initialization (no mlflow workflow)."""

from __future__ import annotations

from pathlib import Path

from qlib.config import C
from qlib.constant import REG_CN
from qlib.data.cache import H
from qlib.data.data import register_all_wrappers
from qlib.data.ops import register_all_ops

_current_provider_uri: str | None = None


def init_qlib(provider_uri: str, *, clear_cache: bool = False) -> None:
    """
    Initialize or re-point qlib to ``provider_uri``.

    Re-initializes when the data directory changes (e.g. day ``qlib/`` vs ``qlib_5m/``),
    so mixed crypto schedules do not keep a stale daily provider for 5m training.
    """
    global _current_provider_uri

    resolved = str(Path(provider_uri).expanduser().resolve())
    provider_changed = _current_provider_uri is not None and _current_provider_uri != resolved
    first_init = not getattr(C, "_registered", False)

    if clear_cache or provider_changed:
        if getattr(C, "_registered", False):
            H.clear()

    if first_init or provider_changed:
        C.set("client", provider_uri=resolved, region=REG_CN, kernels=1)
        register_all_ops(C)
        register_all_wrappers(C)
        C._registered = True
        _current_provider_uri = resolved
    elif clear_cache:
        pass


def reset_qlib_init_state() -> None:
    """Test helper: allow fresh init in unit tests."""
    global _current_provider_uri
    _current_provider_uri = None
    if hasattr(C, "_registered"):
        C._registered = False
