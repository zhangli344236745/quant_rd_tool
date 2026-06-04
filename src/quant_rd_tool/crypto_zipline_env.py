"""Isolated Python env for zipline-reloaded (numpy<2, pandas<2.2)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from quant_rd_tool.config import _project_root

logger = logging.getLogger(__name__)

_VENV_DIR = _project_root() / ".venv-zipline"


def zipline_venv_python() -> Path | None:
    py = _VENV_DIR / "bin" / "python"
    if py.is_file():
        return py
    if sys.platform == "win32":
        py_win = _VENV_DIR / "Scripts" / "python.exe"
        if py_win.is_file():
            return py_win
    return None


def zipline_venv_ready() -> tuple[bool, str | None]:
    py = zipline_venv_python()
    if not py:
        return False, "Zipline venv not created (.venv-zipline)"
    root = _project_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    try:
        proc = subprocess.run(
            [
                str(py),
                "-c",
                "import zipline; from zipline.utils.run_algo import run_algorithm",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "import failed").strip()[:500]
        return True, None
    except Exception as exc:
        return False, str(exc)


def ensure_zipline_venv(*, timeout: int = 600) -> Path:
    """Create .venv-zipline and install zipline-reloaded + compatible numpy/pandas."""
    existing = zipline_venv_python()
    if existing and zipline_venv_ready()[0]:
        return existing

    root = _project_root()
    _VENV_DIR.mkdir(parents=True, exist_ok=True)
    if not ( _VENV_DIR / "pyvenv.cfg").is_file():
        subprocess.run(
            ["uv", "venv", str(_VENV_DIR)],
            cwd=root,
            check=True,
            timeout=120,
        )

    py_target = _VENV_DIR / "bin" / "python"
    if sys.platform == "win32":
        py_target = _VENV_DIR / "Scripts" / "python.exe"
    install_cmd = [
        "uv",
        "pip",
        "install",
        "--python",
        str(py_target),
        "zipline-reloaded>=3.0.4",
        "numpy>=1.26,<2",
        "pandas>=2.0,<2.2",
        "exchange-calendars>=4.2.4",
        "empyrical-reloaded>=0.5.7",
    ]
    logger.info("Installing zipline-reloaded into %s", _VENV_DIR)
    proc = subprocess.run(
        install_cmd,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to setup .venv-zipline:\n{proc.stderr or proc.stdout}"
        )
    py = zipline_venv_python()
    if not py:
        raise RuntimeError("Zipline venv python not found after install")
    ok, err = zipline_venv_ready()
    if not ok:
        raise RuntimeError(f"Zipline venv not importable: {err}")
    return py
