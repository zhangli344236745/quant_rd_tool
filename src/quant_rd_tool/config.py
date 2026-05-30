from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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


settings = Settings()
