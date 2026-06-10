from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_root() -> Path:
    # .../quant_rd_tool/src/quant_rd_tool/config.py -> repo root is parents[2]
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Do not depend on process cwd; always load repo-root .env.
        env_file=str(_project_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default="127.0.0.1", validation_alias="QUANT_RD_HOST")
    port: int = Field(default=8765, validation_alias="QUANT_RD_PORT")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    chat_model: str = Field(default="gpt-4o", validation_alias="CHAT_MODEL")
    openai_api_base: str | None = Field(default=None, validation_alias="OPENAI_API_BASE")
    data_provider: str = Field(
        default="auto",
        validation_alias="QUANT_RD_DATA_PROVIDER",
        description="auto | akshare | openbb",
    )
    fred_api_key: str | None = Field(default=None, validation_alias="FRED_API_KEY")
    fmp_api_key: str | None = Field(default=None, validation_alias="FMP_API_KEY")
    binance_api_key: str | None = Field(default=None, validation_alias="BINANCE_API_KEY")
    binance_api_secret: str | None = Field(default=None, validation_alias="BINANCE_API_SECRET")
    binance_testnet: bool = Field(default=False, validation_alias="BINANCE_TESTNET")
    binance_api_base: str | None = Field(default=None, validation_alias="BINANCE_API_BASE")
    http_proxy: str | None = Field(default=None, validation_alias="HTTP_PROXY")
    https_proxy: str | None = Field(default=None, validation_alias="HTTPS_PROXY")
    bark_device_key: str | None = Field(default=None, validation_alias="BARK_DEVICE_KEY")
    bark_server: str | None = Field(
        default=None,
        validation_alias="BARK_SERVER",
        description="Bark API root, default https://api.day.app",
    )
    tavily_api_key: str | None = Field(default=None, validation_alias="TAVILY_API_KEY")
    serpapi_api_key: str | None = Field(default=None, validation_alias="SERPAPI_API_KEY")
    cursor_api_key: str | None = Field(default=None, validation_alias="CURSOR_API_KEY")
    kb_cursor_model: str = Field(default="composer-2.5", validation_alias="KB_CURSOR_MODEL")
    kb_embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias="KB_EMBEDDING_MODEL",
    )
    kb_data_dir: str = Field(default="data/kb", validation_alias="KB_DATA_DIR")
    kb_fallback_openai: bool = Field(default=False, validation_alias="KB_FALLBACK_OPENAI")
    kb_cloud_agent_timeout: float = Field(default=180.0, validation_alias="KB_CLOUD_AGENT_TIMEOUT")
    kb_cursor_api_base: str = Field(
        default="https://api.cursor.com/v1",
        validation_alias="KB_CURSOR_API_BASE",
    )
    kb_agent_backend: str = Field(
        default="auto",
        validation_alias="KB_AGENT_BACKEND",
        description="auto | sdk | rest — Cursor agent transport for KB chat",
    )


settings = Settings()


def project_root() -> Path:
    return _project_root()
