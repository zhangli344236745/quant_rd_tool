"""Local watchlist persistence for A-share workbench."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path("data/stocks/watchlist.json")


class Watchlist:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or _DEFAULT_PATH)

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"updated_at": None, "items": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = datetime.now(UTC).isoformat()
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_items(self) -> list[dict[str, str]]:
        return list(self._load().get("items") or [])

    def list_codes(self) -> list[str]:
        return [str(it.get("code") or "") for it in self.list_items() if it.get("code")]

    def add(self, code: str, *, name: str = "") -> dict[str, str]:
        code = str(code).strip()
        data = self._load()
        items: list[dict[str, str]] = list(data.get("items") or [])
        for it in items:
            if it.get("code") == code:
                if name and not it.get("name"):
                    it["name"] = name
                self._save(data)
                return it
        row = {
            "code": code,
            "name": name or "",
            "added_at": datetime.now(UTC).isoformat(),
        }
        items.append(row)
        data["items"] = items
        self._save(data)
        return row

    def remove(self, code: str) -> bool:
        code = str(code).strip()
        data = self._load()
        items = [it for it in data.get("items") or [] if it.get("code") != code]
        if len(items) == len(data.get("items") or []):
            return False
        data["items"] = items
        self._save(data)
        return True
