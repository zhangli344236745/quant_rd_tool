from datetime import date
from unittest.mock import MagicMock, patch

from quant_rd_tool.binance_perp_bot import BinancePerpBot, PerpBotConfig
from quant_rd_tool.perp_state import PerpSymbolState


def test_dry_run_reports_circuit_when_would_block(tmp_path):
    prot_path = tmp_path / "prot.json"
    st = PerpSymbolState(
        daily_date="2026-05-28",
        daily_start_usdt_total=1000.0,
        soft_protection_active=True,
        soft_sl_price=90.0,
        soft_tp_price=110.0,
        soft_position_side="long",
    )
    st.save(prot_path)

    cfg = PerpBotConfig(
        base="BTC",
        dry_run=True,
        max_daily_loss_pct=0.03,
        protection_state_path=str(prot_path),
        state_path=str(tmp_path / "trade.json"),
    )
    bot = BinancePerpBot(cfg)

    with patch.object(bot, "fetch_signal", return_value={
        "signal": {"action": "buy"},
        "period": {"end": "2026-05-28 12:00:00"},
    }):
        out = bot.run_once()

    assert out["soft_protection"]["active"] is True
    assert "circuit_breaker" in out


def test_circuit_breaker_blocks_open_in_execute_cycle(tmp_path):
    today = date.today().isoformat()
    prot_path = tmp_path / "prot.json"
    PerpSymbolState(
        daily_date=today,
        daily_start_usdt_total=1000.0,
    ).save(prot_path)

    cfg = PerpBotConfig(
        base="BTC",
        dry_run=False,
        max_daily_loss_pct=0.03,
        protection_state_path=str(prot_path),
        api_key="k",
        api_secret="s",
    )
    bot = BinancePerpBot(cfg)

    mock_ex = MagicMock()
    mock_ex.load_markets.return_value = None
    mock_ex.fetch_positions.return_value = []
    mock_ex.fetch_ticker.return_value = {"last": 100.0}

    with patch.object(bot, "_exchange", return_value=mock_ex):
        close, open_o, _, meta = bot._execute_cycle(
            "long",
            {"USDT_total": 960.0, "USDT_free": 960.0},
        )

    assert meta["circuit_breaker"]["blocked"] is True
    assert open_o is None
    mock_ex.create_order.assert_not_called()
