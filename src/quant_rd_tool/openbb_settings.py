"""Apply API keys from quant-rd settings / env to OpenBB."""

from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)

# OpenBB credential id → env var (uppercase)
_CRED_ENV_MAP = {
    "fred_api_key": "FRED_API_KEY",
    "fmp_api_key": "FMP_API_KEY",
    "econdb_api_key": "ECONDB_API_KEY",
    "tiingo_token": "TIINGO_TOKEN",
}


def configure_openbb_credentials(
    *,
    fred_api_key: str | None = None,
    fmp_api_key: str | None = None,
) -> dict[str, bool]:
    """
    Push keys into process env for OpenBB providers (idempotent).

    Returns which providers appear configured after this call.
    """
    from quant_rd_tool.config import settings

    pairs = {
        "fred_api_key": fred_api_key or settings.fred_api_key,
        "fmp_api_key": fmp_api_key or settings.fmp_api_key,
    }
    for cred_key, value in pairs.items():
        if not value:
            continue
        env_name = _CRED_ENV_MAP[cred_key]
        if not os.environ.get(env_name):
            os.environ[env_name] = value.strip()
            logger.debug("Set %s for OpenBB", env_name)

    return {
        "fred": bool(os.environ.get("FRED_API_KEY")),
        "fmp": bool(os.environ.get("FMP_API_KEY")),
    }
