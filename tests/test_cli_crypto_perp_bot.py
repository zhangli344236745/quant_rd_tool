import subprocess


def test_crypto_perp_bot_help():
    proc = subprocess.run(
        ["uv", "run", "quant-rd", "crypto", "perp-bot", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "perp-bot" in (proc.stdout + proc.stderr)

