from unittest.mock import patch

from quant_rd_tool.crypto_ops_control import (
    get_crypto_ops,
    is_kill_switch_active,
    save_crypto_ops,
    should_notify_webhook,
)


def test_kill_switch_persist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert not is_kill_switch_active()
    save_crypto_ops(kill_switch=True)
    assert is_kill_switch_active()
    save_crypto_ops(kill_switch=False)
    assert not is_kill_switch_active()


def test_should_notify_webhook():
    ops = {
        "webhook_url": "https://example.com/hook",
        "webhook_on_error": True,
        "webhook_on_circuit_breaker": True,
    }
    assert should_notify_webhook({"decision": "error"}, ops)
    assert should_notify_webhook({"decision": "blocked_circuit_breaker"}, ops)
    assert not should_notify_webhook({"decision": "opened"}, ops)


def test_perp_bot_kill_switch_blocks_live(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_crypto_ops(kill_switch=True)
    settings_path = tmp_path / "data" / "settings.json"
    assert settings_path.is_file()

    from quant_rd_tool.binance_perp_bot import BinancePerpBot, PerpBotConfig

    bot = BinancePerpBot(
        PerpBotConfig(
            base="BTC",
            dry_run=False,
            telemetry_enabled=False,
        )
    )

    def fake_signal():
        return {
            "signal": {"action": "hold"},
            "period": {"end": "2026-05-29T12:00:00Z"},
        }

    monkeypatch.setattr(bot, "fetch_signal", fake_signal)
    out = bot.run_once()
    assert out.get("kill_switch", {}).get("active") is True
    assert "Kill Switch" in out.get("message", "")


def test_post_webhook_mock():
    with patch("httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        from quant_rd_tool.crypto_ops_control import post_webhook

        post_webhook("https://hooks.example/x", {"decision": "error", "base": "BTC"})
        client.post.assert_called_once()
