from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from quant_rd_tool.crypto_options_spread_alerts import (
    evaluate_compare_item,
    fire_spread_alert,
    get_spread_alert_config,
    process_spread_alerts,
    save_spread_alert_config,
    tail_spread_alert_log,
)


def test_config_roundtrip(tmp_path: Path):
    data_dir = tmp_path / "crypto"
    data_dir.mkdir(parents=True)
    save_spread_alert_config(data_dir=str(data_dir), hot_pp=6.0, elevated_pp=3.0)
    cfg = get_spread_alert_config(str(data_dir))
    assert cfg["hot_pp"] == 6.0
    assert cfg["elevated_pp"] == 3.0


def test_evaluate_hot_triggers(monkeypatch, tmp_path: Path):
    data_dir = str(tmp_path / "crypto")
    save_spread_alert_config(data_dir=data_dir, cooldown_minutes=60)
    item = {
        "base": "BTC",
        "aligned": {
            "available": True,
            "expiry_date": "2026-06-27",
            "comparison": {
                "iv_spread_pp": 6.0,
                "abs_spread_pp": 6.0,
                "richer_venue": "binance",
                "summary": "test",
            },
        },
    }
    fired: list[bool] = []

    def fake_fire(**kwargs):
        fired.append(True)
        return True

    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_spread_alerts.fire_spread_alert",
        fake_fire,
    )
    r = evaluate_compare_item(item, data_dir=data_dir)
    assert r
    assert r["level"] == "hot"
    assert fired


def test_cooldown_blocks_second_fire(tmp_path: Path, monkeypatch):
    data_dir = str(tmp_path / "crypto")
    state = tmp_path / "options_spread_alert_state.json"
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_spread_alerts._STATE_PATH",
        state,
    )
    log = tmp_path / "options_spread_alert_log.jsonl"
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_spread_alerts._LOG_PATH",
        log,
    )
    save_spread_alert_config(data_dir=data_dir, cooldown_minutes=999)
    with patch(
        "quant_rd_tool.crypto_options_spread_alerts._deliver_notification"
    ) as deliver:
        assert fire_spread_alert(
            base="ETH",
            level="elevated",
            message="m1",
            data_dir=data_dir,
        )
        assert not fire_spread_alert(
            base="ETH",
            level="elevated",
            message="m2",
            data_dir=data_dir,
        )
        assert deliver.call_count == 1
    items = tail_spread_alert_log(log_path=log)
    assert len(items) == 1


def test_process_spread_alerts_summary():
    pack = {
        "items": [
            {
                "base": "SOL",
                "comparison": {"available": True, "abs_spread_pp": 1.0, "iv_spread_pp": 1.0},
            },
            {
                "base": "BTC",
                "aligned": {
                    "available": True,
                    "expiry_date": "2026-06-27",
                    "comparison": {
                        "iv_spread_pp": 3.5,
                        "abs_spread_pp": 3.5,
                        "richer_venue": "binance",
                    },
                },
            },
        ]
    }
    with patch(
        "quant_rd_tool.crypto_options_spread_alerts.fire_spread_alert",
        return_value=True,
    ):
        out = process_spread_alerts(pack, data_dir="data/crypto")
    assert out["checked"] == 2
    assert out["triggered"] == 1
