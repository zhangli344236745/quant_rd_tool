from __future__ import annotations

import hashlib
import re
from typing import Literal

TargetSide = Literal["long", "short", "flat"]

_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")


def build_client_order_id(*, symbol: str, bar_end: str, target_side: TargetSide) -> str:
    """
    Deterministic short clientOrderId for Binance futures.

    Constraints:
    - Keyed by (symbol, bar_end, target_side)
    - Charset: [A-Za-z0-9_-]
    - Length <= 36
    """
    base = f"{symbol}|{bar_end}|{target_side}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()  # stable and short
    # Prefix for readability; keep under 36 chars total.
    cid = f"qrdp_{digest[:30]}"
    cid = _SAFE_RE.sub("_", cid)
    return cid[:36]

