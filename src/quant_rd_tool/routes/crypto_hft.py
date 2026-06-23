"""API routes for crypto market-making (HFT v1)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class HftBotUpsert(BaseModel):
    bot_id: str
    symbol: str = "BTC"
    quote: str = "USDT"
    market_type: str = "future"
    strategy_id: str = "classic_mm"
    strategy_params: dict[str, Any] | None = None
    testnet: bool = True
    interval_ms: int = Field(default=1500, ge=1000, le=60_000)
    book_depth: int = Field(default=5, ge=1, le=20)
    price_tolerance_bps: float = Field(default=3.0, ge=0.5, le=50)
    post_only: bool = True
    max_order_size_usdt: float = Field(default=500.0, gt=0)
    max_open_orders: int = Field(default=20, ge=1, le=50)
    maker_fee_bps: float = Field(default=2.0, ge=0, le=50)
    min_edge_bps: float = Field(default=1.0, ge=0, le=50)
    use_client_order_tags: bool = True
    batch_cancel: bool = True
    max_session_loss_usdt: float = Field(default=0.0, ge=0)
    max_inventory_usdt: float = Field(default=0.0, ge=0)


class HftGlobalConfigUpdate(BaseModel):
    default_testnet: bool | None = None
    default_interval_ms: int | None = Field(default=None, ge=1000, le=60_000)
    max_daily_loss_usdt: float | None = Field(default=None, gt=0)


class HftStartRequest(BaseModel):
    confirm_mainnet: bool = False


@router.get("/strategies")
def hft_strategies() -> list[dict[str, Any]]:
    from quant_rd_tool.crypto_hft_strategies import list_strategies

    return list_strategies()


@router.get("/config")
def hft_get_config() -> dict[str, Any]:
    from quant_rd_tool.crypto_hft_storage import list_bot_ids, load_global_config

    return {"global": load_global_config().__dict__, "bot_ids": list_bot_ids()}


@router.put("/config")
def hft_put_config(body: HftGlobalConfigUpdate) -> dict[str, Any]:
    from quant_rd_tool.crypto_hft_storage import HftGlobalConfig, load_global_config, save_global_config

    cfg = load_global_config()
    for key, val in body.model_dump(exclude_none=True).items():
        if hasattr(cfg, key):
            setattr(cfg, key, val)
    return save_global_config(cfg)


@router.get("/bots")
def hft_list_bots() -> dict[str, Any]:
    from quant_rd_tool.crypto_hft_runner import get_hft_manager

    return {"items": get_hft_manager().status()}


@router.post("/bots")
def hft_upsert_bot(body: HftBotUpsert) -> dict[str, Any]:
    from quant_rd_tool.crypto_hft_runner import get_hft_manager
    from quant_rd_tool.crypto_hft_storage import HftBotConfig

    if body.market_type not in ("spot", "future"):
        raise HTTPException(status_code=400, detail="market_type must be spot or future")
    cfg = HftBotConfig(
        bot_id=body.bot_id,
        symbol=body.symbol,
        quote=body.quote,
        market_type=body.market_type,  # type: ignore[arg-type]
        strategy_id=body.strategy_id,
        strategy_params=body.strategy_params or {},
        testnet=body.testnet,
        interval_ms=body.interval_ms,
        book_depth=body.book_depth,
        price_tolerance_bps=body.price_tolerance_bps,
        post_only=body.post_only,
        max_order_size_usdt=body.max_order_size_usdt,
        max_open_orders=body.max_open_orders,
        maker_fee_bps=body.maker_fee_bps,
        min_edge_bps=body.min_edge_bps,
        use_client_order_tags=body.use_client_order_tags,
        batch_cancel=body.batch_cancel,
        max_session_loss_usdt=body.max_session_loss_usdt,
        max_inventory_usdt=body.max_inventory_usdt,
    )
    try:
        return get_hft_manager().register(cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/bots/{bot_id}")
def hft_delete_bot(bot_id: str) -> dict[str, Any]:
    from quant_rd_tool.crypto_hft_runner import get_hft_manager

    try:
        return get_hft_manager().remove(bot_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/bots/{bot_id}/status")
def hft_bot_status(bot_id: str) -> dict[str, Any]:
    from quant_rd_tool.crypto_hft_runner import get_hft_manager

    try:
        return get_hft_manager().status_one(bot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/bots/{bot_id}/start")
def hft_bot_start(bot_id: str, body: HftStartRequest | None = None) -> dict[str, Any]:
    from quant_rd_tool.crypto_hft_runner import get_hft_manager

    req = body or HftStartRequest()
    try:
        return get_hft_manager().start(bot_id, confirm_mainnet=req.confirm_mainnet)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/bots/{bot_id}/stop")
def hft_bot_stop(bot_id: str, cancel_orders: bool = Query(default=False)) -> dict[str, Any]:
    from quant_rd_tool.crypto_hft_runner import get_hft_manager

    try:
        return get_hft_manager().stop(bot_id, cancel_orders=cancel_orders)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/bots/{bot_id}/cycle")
def hft_bot_cycle(bot_id: str) -> dict[str, Any]:
    from quant_rd_tool.crypto_hft_runner import get_hft_manager

    try:
        return get_hft_manager().run_once(bot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/bots/{bot_id}/pnl")
def hft_bot_pnl(bot_id: str) -> dict[str, Any]:
    from quant_rd_tool.crypto_hft_risk import risk_summary
    from quant_rd_tool.crypto_hft_storage import load_bot_state, validate_bot_id

    bid = validate_bot_id(bot_id)
    state = load_bot_state(bid)
    return {
        "bot_id": bid,
        **risk_summary(state),
        "pnl_snapshots": state.get("pnl_snapshots") or [],
    }


@router.get("/bots/{bot_id}/events")
def hft_bot_events(bot_id: str, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    from quant_rd_tool.crypto_hft_storage import tail_events

    try:
        return {"items": tail_events(bot_id, limit=limit)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/book")
def hft_book_snapshot(
    symbol: str,
    market_type: str = "future",
    quote: str = "USDT",
    testnet: bool = True,
    depth: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    from quant_rd_tool.crypto_hft import fetch_book_snapshot

    if market_type not in ("spot", "future"):
        raise HTTPException(status_code=400, detail="market_type must be spot or future")
    try:
        return fetch_book_snapshot(
            symbol=symbol,
            market_type=market_type,
            quote=quote,
            testnet=testnet,
            book_depth=depth,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
