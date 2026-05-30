import subprocess


def test_crypto_perp_portfolio_help():
    proc = subprocess.run(
        ["uv", "run", "quant-rd", "crypto", "perp-portfolio", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "perp-portfolio" in (proc.stdout + proc.stderr)
