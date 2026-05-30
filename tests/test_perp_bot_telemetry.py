import json
from unittest.mock import patch

from quant_rd_tool.binance_perp_bot import BinancePerpBot, PerpBotConfig


def test_run_once_dry_run_writes_jsonl(tmp_path):
    tel_dir = tmp_path / "logs"
    cfg = PerpBotConfig(
        base="BTC",
        dry_run=True,
        telemetry_enabled=True,
        telemetry_log_dir=str(tel_dir),
        state_path=str(tmp_path / "state.json"),
        protection_state_path=str(tmp_path / "prot.json"),
    )
    bot = BinancePerpBot(cfg)

    with patch.object(
        bot,
        "fetch_signal",
        return_value={
            "signal": {"action": "hold", "score": 0, "confidence": 0.1},
            "period": {"end": "2026-05-28 12:05:00"},
        },
    ):
        out = bot.run_once()

    assert out.get("decision") == "no_op"
    files = list(tel_dir.glob("*.jsonl"))
    assert len(files) == 1
    row = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert row["kind"] == "cycle"
    assert row["decision"] == "no_op"
