"""Market-making quote generators for crypto HFT module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from quant_rd_tool.crypto_hft_market_signals import (
    book_imbalance,
    imbalance_shift_bps,
    realized_vol_bps,
    update_mid_history,
)

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Quote:
    side: Side
    price: float
    amount: float
    level: int = 0
    tag: str = ""


def _mid_from_book(book: dict[str, Any]) -> float:
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        raise ValueError("order book empty")
    return (float(bids[0][0]) + float(asks[0][0])) / 2.0


def _bps_to_ratio(bps: float) -> float:
    return float(bps) / 10_000.0


def _merge_params(strategy_id: str, params: dict[str, Any] | None) -> dict[str, Any]:
    spec = _STRATEGIES[strategy_id]
    return {**spec["default_params"], **(params or {})}


def _quote_size(amount_usdt: float, price: float) -> float:
    if price <= 0:
        return 0.0
    return round(amount_usdt / price, 8)


def _inventory_ratio(inventory_usdt: float, max_inv: float) -> float:
    if max_inv <= 0:
        return 0.0
    return max(-1.0, min(1.0, inventory_usdt / max_inv))


_STRATEGIES: dict[str, dict[str, Any]] = {
    "classic_mm": {
        "id": "classic_mm",
        "name": "经典双边做市",
        "description": "mid ± spread，库存偏斜，可选多层",
        "default_params": {
            "half_spread_bps": 8.0,
            "order_size_usdt": 50.0,
            "levels": 1,
            "level_step_bps": 5.0,
            "inventory_skew_bps": 4.0,
            "max_inventory_usdt": 500.0,
            "min_spread_bps": 4.0,
        },
        "param_schema": [
            {"name": "half_spread_bps", "type": "float", "min": 2, "max": 100, "default": 8, "label": "半价差 bps"},
            {"name": "levels", "type": "int", "min": 1, "max": 5, "default": 1, "label": "每侧层数"},
            {"name": "level_step_bps", "type": "float", "min": 2, "max": 50, "default": 5, "label": "层间距 bps"},
            {"name": "order_size_usdt", "type": "float", "min": 5, "max": 5000, "default": 50, "label": "单边名义 USDT"},
            {"name": "inventory_skew_bps", "type": "float", "min": 0, "max": 50, "default": 4, "label": "库存偏斜 bps"},
            {"name": "max_inventory_usdt", "type": "float", "min": 10, "max": 50000, "default": 500, "label": "最大库存 USDT"},
        ],
    },
    "grid_mm": {
        "id": "grid_mm",
        "name": "网格做市",
        "description": "围绕中心价多层买卖限价",
        "default_params": {
            "grid_spacing_bps": 15.0,
            "grid_levels": 5,
            "order_size_usdt": 30.0,
            "max_inventory_usdt": 1000.0,
            "reanchor_bps": 200.0,
        },
        "param_schema": [
            {"name": "grid_spacing_bps", "type": "float", "min": 5, "max": 200, "default": 15, "label": "网格间距 bps"},
            {"name": "grid_levels", "type": "int", "min": 1, "max": 10, "default": 5, "label": "每侧层数"},
            {"name": "order_size_usdt", "type": "float", "min": 5, "max": 5000, "default": 30, "label": "每层名义 USDT"},
            {"name": "max_inventory_usdt", "type": "float", "min": 10, "max": 50000, "default": 1000, "label": "最大库存 USDT"},
        ],
    },
    "vol_mm": {
        "id": "vol_mm",
        "name": "波动率自适应",
        "description": "根据 mid 历史实现波动率动态加宽价差",
        "default_params": {
            "base_half_spread_bps": 6.0,
            "vol_sensitivity": 0.35,
            "min_half_spread_bps": 4.0,
            "max_half_spread_bps": 40.0,
            "order_size_usdt": 50.0,
            "levels": 1,
            "inventory_skew_bps": 4.0,
            "max_inventory_usdt": 500.0,
            "vol_lookback": 30,
        },
        "param_schema": [
            {"name": "base_half_spread_bps", "type": "float", "min": 2, "max": 50, "default": 6, "label": "基础半价差 bps"},
            {"name": "vol_sensitivity", "type": "float", "min": 0, "max": 2, "default": 0.35, "label": "波动敏感度"},
            {"name": "max_half_spread_bps", "type": "float", "min": 5, "max": 100, "default": 40, "label": "最大半价差 bps"},
            {"name": "order_size_usdt", "type": "float", "min": 5, "max": 5000, "default": 50, "label": "单边名义 USDT"},
            {"name": "inventory_skew_bps", "type": "float", "min": 0, "max": 50, "default": 4, "label": "库存偏斜 bps"},
            {"name": "max_inventory_usdt", "type": "float", "min": 10, "max": 50000, "default": 500, "label": "最大库存 USDT"},
        ],
    },
    "imbalance_mm": {
        "id": "imbalance_mm",
        "name": "盘口失衡做市",
        "description": "按买卖盘量失衡偏移保留价，捕捉微观结构",
        "default_params": {
            "half_spread_bps": 8.0,
            "imbalance_depth": 5,
            "max_imbalance_skew_bps": 12.0,
            "order_size_usdt": 50.0,
            "levels": 2,
            "level_step_bps": 6.0,
            "inventory_skew_bps": 4.0,
            "max_inventory_usdt": 500.0,
        },
        "param_schema": [
            {"name": "half_spread_bps", "type": "float", "min": 2, "max": 100, "default": 8, "label": "半价差 bps"},
            {"name": "imbalance_depth", "type": "int", "min": 1, "max": 20, "default": 5, "label": "盘口深度档"},
            {"name": "max_imbalance_skew_bps", "type": "float", "min": 0, "max": 50, "default": 12, "label": "失衡偏斜 bps"},
            {"name": "levels", "type": "int", "min": 1, "max": 5, "default": 2, "label": "每侧层数"},
            {"name": "order_size_usdt", "type": "float", "min": 5, "max": 5000, "default": 50, "label": "单边名义 USDT"},
            {"name": "max_inventory_usdt", "type": "float", "min": 10, "max": 50000, "default": 500, "label": "最大库存 USDT"},
        ],
    },
    "as_mm": {
        "id": "as_mm",
        "name": "AS 简化做市",
        "description": "Avellaneda-Stoikov 简化：保留价 + 波动/库存价差",
        "default_params": {
            "gamma": 0.35,
            "kappa_bps": 8.0,
            "vol_weight": 0.25,
            "order_size_usdt": 50.0,
            "levels": 1,
            "max_inventory_usdt": 500.0,
            "vol_lookback": 30,
        },
        "param_schema": [
            {"name": "gamma", "type": "float", "min": 0.05, "max": 2, "default": 0.35, "label": "风险厌恶 γ"},
            {"name": "kappa_bps", "type": "float", "min": 2, "max": 50, "default": 8, "label": "基础半价差 κ bps"},
            {"name": "vol_weight", "type": "float", "min": 0, "max": 2, "default": 0.25, "label": "波动权重"},
            {"name": "order_size_usdt", "type": "float", "min": 5, "max": 5000, "default": 50, "label": "单边名义 USDT"},
            {"name": "max_inventory_usdt", "type": "float", "min": 10, "max": 50000, "default": 500, "label": "最大库存 USDT"},
        ],
    },
}


def list_strategies() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in _STRATEGIES.values():
        out.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "description": spec["description"],
                "default_params": dict(spec["default_params"]),
                "param_schema": spec["param_schema"],
            }
        )
    return out


def get_strategy(strategy_id: str) -> dict[str, Any]:
    sid = strategy_id.strip()
    if sid not in _STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy_id}")
    spec = _STRATEGIES[sid]
    return {
        "id": spec["id"],
        "name": spec["name"],
        "description": spec["description"],
        "default_params": dict(spec["default_params"]),
        "param_schema": spec["param_schema"],
    }


def build_quotes(
    strategy_id: str,
    book: dict[str, Any],
    *,
    inventory_usdt: float = 0.0,
    params: dict[str, Any] | None = None,
    center_price: float | None = None,
    state: dict[str, Any] | None = None,
) -> list[Quote]:
    sid = strategy_id.strip()
    if sid not in _STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy_id}")
    merged = _merge_params(sid, params)
    mid = center_price if center_price and center_price > 0 else _mid_from_book(book)
    st = state or {}
    hist = update_mid_history(st, mid, max_samples=int(merged.get("vol_lookback", 60)))
    vol_bps = realized_vol_bps(hist)

    if sid == "classic_mm":
        return _classic_quotes(mid, inventory_usdt, merged)
    if sid == "grid_mm":
        return _grid_quotes(mid, inventory_usdt, merged)
    if sid == "vol_mm":
        return _vol_quotes(mid, inventory_usdt, merged, vol_bps=vol_bps)
    if sid == "imbalance_mm":
        return _imbalance_quotes(mid, inventory_usdt, merged, book=book)
    if sid == "as_mm":
        return _as_quotes(mid, inventory_usdt, merged, vol_bps=vol_bps)
    raise ValueError(f"unknown strategy: {strategy_id}")


def _classic_quotes(mid: float, inventory_usdt: float, p: dict[str, Any]) -> list[Quote]:
    half = _bps_to_ratio(p["half_spread_bps"])
    min_half = _bps_to_ratio(float(p.get("min_spread_bps", 0))) / 2
    half = max(half, min_half)
    skew_ratio = _bps_to_ratio(p["inventory_skew_bps"])
    max_inv = float(p["max_inventory_usdt"])
    size_usdt = float(p["order_size_usdt"])
    levels = max(1, int(p.get("levels", 1)))
    step = _bps_to_ratio(p.get("level_step_bps", 5.0))
    inv_ratio = _inventory_ratio(inventory_usdt, max_inv)
    shift = skew_ratio * inv_ratio * mid
    quotes: list[Quote] = []
    for lvl in range(levels):
        offset = half + step * lvl
        bid_px = mid * (1 - offset) - shift
        ask_px = mid * (1 + offset) - shift
        if inventory_usdt < max_inv and bid_px > 0:
            quotes.append(
                Quote(
                    side="buy",
                    price=round(bid_px, 8),
                    amount=_quote_size(size_usdt, bid_px),
                    level=lvl,
                    tag=f"classic_bid_{lvl}",
                )
            )
        if inventory_usdt > -max_inv and ask_px > 0:
            quotes.append(
                Quote(
                    side="sell",
                    price=round(ask_px, 8),
                    amount=_quote_size(size_usdt, ask_px),
                    level=lvl,
                    tag=f"classic_ask_{lvl}",
                )
            )
    return quotes


def _grid_quotes(mid: float, inventory_usdt: float, p: dict[str, Any]) -> list[Quote]:
    spacing = _bps_to_ratio(p["grid_spacing_bps"])
    levels = int(p["grid_levels"])
    size_usdt = float(p["order_size_usdt"])
    max_inv = float(p["max_inventory_usdt"])
    quotes: list[Quote] = []
    for i in range(1, levels + 1):
        bid_px = mid * (1 - spacing * i)
        ask_px = mid * (1 + spacing * i)
        if inventory_usdt < max_inv and bid_px > 0:
            quotes.append(
                Quote(
                    side="buy",
                    price=round(bid_px, 8),
                    amount=_quote_size(size_usdt, bid_px),
                    level=i,
                    tag=f"grid_bid_{i}",
                )
            )
        if inventory_usdt > -max_inv and ask_px > 0:
            quotes.append(
                Quote(
                    side="sell",
                    price=round(ask_px, 8),
                    amount=_quote_size(size_usdt, ask_px),
                    level=i,
                    tag=f"grid_ask_{i}",
                )
            )
    return quotes


def _vol_quotes(mid: float, inventory_usdt: float, p: dict[str, Any], *, vol_bps: float) -> list[Quote]:
    base_half = float(p["base_half_spread_bps"])
    sens = float(p["vol_sensitivity"])
    min_half = float(p["min_half_spread_bps"])
    max_half = float(p["max_half_spread_bps"])
    half_bps = base_half + sens * vol_bps
    half_bps = max(min_half, min(max_half, half_bps))
    merged = {**p, "half_spread_bps": half_bps, "levels": int(p.get("levels", 1))}
    return _classic_quotes(mid, inventory_usdt, merged)


def _imbalance_quotes(
    mid: float,
    inventory_usdt: float,
    p: dict[str, Any],
    *,
    book: dict[str, Any],
) -> list[Quote]:
    depth = int(p.get("imbalance_depth", 5))
    imb = book_imbalance(book, depth=depth)
    shift_bps = imbalance_shift_bps(imb, float(p["max_imbalance_skew_bps"]))
    reservation = mid * (1 + _bps_to_ratio(shift_bps))
    half = _bps_to_ratio(p["half_spread_bps"])
    skew_ratio = _bps_to_ratio(p["inventory_skew_bps"])
    max_inv = float(p["max_inventory_usdt"])
    size_usdt = float(p["order_size_usdt"])
    levels = max(1, int(p.get("levels", 1)))
    step = _bps_to_ratio(p.get("level_step_bps", 6.0))
    inv_ratio = _inventory_ratio(inventory_usdt, max_inv)
    inv_shift = skew_ratio * inv_ratio * reservation
    quotes: list[Quote] = []
    for lvl in range(levels):
        offset = half + step * lvl
        bid_px = reservation * (1 - offset) - inv_shift
        ask_px = reservation * (1 + offset) - inv_shift
        if inventory_usdt < max_inv and bid_px > 0:
            quotes.append(
                Quote(
                    side="buy",
                    price=round(bid_px, 8),
                    amount=_quote_size(size_usdt, bid_px),
                    level=lvl,
                    tag=f"imb_bid_{lvl}",
                )
            )
        if inventory_usdt > -max_inv and ask_px > 0:
            quotes.append(
                Quote(
                    side="sell",
                    price=round(ask_px, 8),
                    amount=_quote_size(size_usdt, ask_px),
                    level=lvl,
                    tag=f"imb_ask_{lvl}",
                )
            )
    return quotes


def _as_quotes(mid: float, inventory_usdt: float, p: dict[str, Any], *, vol_bps: float) -> list[Quote]:
    gamma = float(p["gamma"])
    kappa_bps = float(p["kappa_bps"])
    vol_weight = float(p["vol_weight"])
    max_inv = float(p["max_inventory_usdt"])
    size_usdt = float(p["order_size_usdt"])
    levels = max(1, int(p.get("levels", 1)))

    inv_ratio = _inventory_ratio(inventory_usdt, max_inv)
    sigma = vol_bps / 10_000.0
    reservation = mid - inv_ratio * gamma * sigma * mid
    half_bps = kappa_bps + vol_weight * vol_bps + gamma * abs(inv_ratio) * vol_bps
    half = _bps_to_ratio(half_bps)

    quotes: list[Quote] = []
    for lvl in range(levels):
        step = half * (1 + 0.5 * lvl)
        bid_px = reservation * (1 - step)
        ask_px = reservation * (1 + step)
        if inventory_usdt < max_inv and bid_px > 0:
            quotes.append(
                Quote(
                    side="buy",
                    price=round(bid_px, 8),
                    amount=_quote_size(size_usdt, bid_px),
                    level=lvl,
                    tag=f"as_bid_{lvl}",
                )
            )
        if inventory_usdt > -max_inv and ask_px > 0:
            quotes.append(
                Quote(
                    side="sell",
                    price=round(ask_px, 8),
                    amount=_quote_size(size_usdt, ask_px),
                    level=lvl,
                    tag=f"as_ask_{lvl}",
                )
            )
    return quotes
