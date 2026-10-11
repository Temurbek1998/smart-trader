from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Candle(Base):
    """Narx shami (OHLCV). PostgreSQL'da TimescaleDB hypertable bo'ladi."""

    __tablename__ = "candles"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "ts"),)

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(4), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)


class Analysis(Base):
    """Claude'ning har bir chaqiruvi: nimani ko'rdi, nima dedi, qancha turdi."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    symbol: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))  # monitor | deep
    strategy: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str] = mapped_column(String(60))
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict] = mapped_column(JSON)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"))
    strategy: Mapped[str] = mapped_column(String(40))
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(4))  # BUY | SELL | HOLD
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    timeframes_agree: Mapped[bool] = mapped_column(default=False)
    published: Mapped[bool] = mapped_column(default=False)  # ishonch qoidasidan o'tdimi
    reason: Mapped[str] = mapped_column(Text, default="")


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"))
    strategy: Mapped[str] = mapped_column(String(40))
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="OPEN")  # OPEN | TP | SL


def make_engine(url: str | None = None):
    url = url or settings.database_url
    return create_engine(url, future=True)


engine = make_engine()
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db(eng=None) -> None:
    eng = eng or engine
    Base.metadata.create_all(eng)
    if eng.dialect.name == "postgresql":
        with eng.begin() as conn:
            has_ts = conn.execute(
                text("SELECT 1 FROM pg_available_extensions WHERE name='timescaledb'")
            ).first()
            if has_ts:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
                conn.execute(
                    text(
                        "SELECT create_hypertable('candles', 'ts', "
                        "if_not_exists => TRUE, migrate_data => TRUE)"
                    )
                )
