import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _db_url() -> str:
    """Neon/Vercel beradigan postgres:// manzilni SQLAlchemy + psycopg formatiga o'tkazadi."""
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or "sqlite:///smart_trader.db"
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _f(name: str, default: str) -> float:
    return float(os.getenv(name) or default)


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    database_url: str = _db_url()
    data_provider: str = os.getenv("DATA_PROVIDER", "yahoo").lower()
    symbol: str = os.getenv("SYMBOL", "XAUUSD")

    mt5_login: str = os.getenv("MT5_LOGIN", "")
    mt5_password: str = os.getenv("MT5_PASSWORD", "")
    mt5_server: str = os.getenv("MT5_SERVER", "")
    mt5_path: str = os.getenv("MT5_PATH", "")

    analyst_model: str = os.getenv("ANALYST_MODEL", "claude-opus-5-5")
    monitor_model: str = os.getenv("MONITOR_MODEL", "claude-haiku-5-5")
    analyst_effort: str = os.getenv("ANALYST_EFFORT", "high")

    min_confidence: float = _f("MIN_CONFIDENCE", "0.7")
    daily_cost_limit_usd: float = _f("DAILY_COST_LIMIT_USD", "20")

    paper_balance: float = _f("PAPER_BALANCE", "10000")
    risk_per_trade: float = _f("RISK_PER_TRADE", "0.01")
    execute_on_mt5: bool = os.getenv("EXECUTE_ON_MT5", "false").lower() == "true"

    monitor_every_min: int = int(os.getenv("MONITOR_EVERY_MIN", "5"))


settings = Settings()
