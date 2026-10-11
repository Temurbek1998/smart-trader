"""Shamlarni bazaga yozish va o'qish."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.providers import COLUMNS, resample
from app.db import Candle


def _insert(session: Session):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


def upsert_candles(session: Session, symbol: str, timeframe: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "ts": ts.to_pydatetime(),
            **{c: float(r[c]) for c in COLUMNS},
        }
        for ts, r in df.iterrows()
    ]
    insert = _insert(session)
    for i in range(0, len(rows), 2000):
        stmt = insert(Candle).values(rows[i : i + 2000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "ts"],
            set_={c: getattr(stmt.excluded, c) for c in COLUMNS},
        )
        session.execute(stmt)
    session.commit()
    return len(rows)


def load_candles(
    session: Session,
    symbol: str,
    timeframe: str,
    limit: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    q = select(Candle).where(Candle.symbol == symbol, Candle.timeframe == timeframe)
    if start:
        q = q.where(Candle.ts >= start)
    if end:
        q = q.where(Candle.ts <= end)
    q = q.order_by(Candle.ts.desc())
    if limit:
        q = q.limit(limit)
    rows = session.scalars(q).all()
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(
        [{"ts": r.ts, **{c: getattr(r, c) for c in COLUMNS}} for r in rows]
    ).set_index("ts")
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def last_ts(session: Session, symbol: str, timeframe: str) -> datetime | None:
    from sqlalchemy import func

    ts = session.scalar(
        select(func.max(Candle.ts)).where(Candle.symbol == symbol, Candle.timeframe == timeframe)
    )
    if ts is not None and ts.tzinfo is None:
        from datetime import timezone

        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def rebuild_yearly(session: Session, symbol: str) -> int:
    """1 yillik shamlarni oylik (MN1) shamlardan hisoblaydi."""
    monthly = load_candles(session, symbol, "MN1")
    if monthly.empty:
        return 0
    return upsert_candles(session, symbol, "Y1", resample(monthly, "YS"))
