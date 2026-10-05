from decimal import Decimal
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://marketbrain:marketbrain@postgres/marketbrain"
    redis_url: str = "redis://redis:6379/0"
    app_origin: str = "http://localhost:3000"
    cookie_secure: bool = True
    session_hours: int = 24
    risk_per_trade: Decimal = Decimal("0.01")
    max_position: Decimal = Decimal("0.15")
    max_exposure: Decimal = Decimal("0.60")
    max_daily_loss: Decimal = Decimal("0.02")
    max_drawdown: Decimal = Decimal("0.08")
    max_positions: int = 4
    max_data_age_seconds: int = 30
    commission_rate: Decimal = Decimal("0.003")
    broker_key_dir: Path = Path("/var/lib/marketbrain/keys")
    broker_token_dir: Path = Path("/var/lib/marketbrain/tokens")
    market_sync_seconds: int = Field(default=300, ge=60, le=3600)
    quote_freshness_seconds: int = Field(default=30, ge=1, le=300)


settings = Settings()
