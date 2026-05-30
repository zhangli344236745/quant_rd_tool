from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TradingState:
    last_seen_bar_end: str = ""
    last_action: str = ""

    @staticmethod
    def load(path: str | Path) -> "TradingState":
        p = Path(path)
        if not p.exists():
            return TradingState()
        raw = p.read_text(encoding="utf-8").strip()
        data = json.loads(raw or "{}")
        return TradingState(
            last_seen_bar_end=str(data.get("last_seen_bar_end") or ""),
            last_action=str(data.get("last_action") or ""),
        )

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {"last_seen_bar_end": self.last_seen_bar_end, "last_action": self.last_action},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

