"""Uzoq tarixni CSV fayldan import qilish (masalan, Dukascopy'dan yuklangan XAUUSD M1).

Foydalanish:
    python -m app.data.import_csv fayl.csv --timeframe M1 [--symbol XAUUSD]

CSV ustunlari: timestamp (yoki time/date), open, high, low, close, volume (ixtiyoriy).
timestamp ISO sana yoki millisekund bo'lishi mumkin. M1 import qilinsa,
undan katta barcha vaqt oraliqlari ham avtomatik hisoblanadi.
"""

from __future__ import annotations

import argparse

import pandas as pd

from app.config import settings
from app.data.providers import resample
from app.data.store import rebuild_yearly, upsert_candles
from app.db import SessionLocal, init_db
from app.timeframes import FETCHED


def read_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next(c for c in ("timestamp", "time", "date", "datetime") if c in df.columns)
    t = df[tcol]
    ts = pd.to_datetime(t, unit="ms", utc=True) if pd.api.types.is_numeric_dtype(t) else pd.to_datetime(t, utc=True)
    df = df.assign(ts=ts).set_index("ts")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df[["open", "high", "low", "close", "volume"]].sort_index()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--timeframe", default="M1")
    p.add_argument("--symbol", default=settings.symbol)
    args = p.parse_args()

    init_db()
    df = read_csv(args.path)
    codes = [tf.code for tf in FETCHED]
    start = codes.index(args.timeframe)
    with SessionLocal() as session:
        for tf in FETCHED[start:]:
            part = df if tf.code == args.timeframe else resample(df, tf.pandas_rule)
            n = upsert_candles(session, args.symbol, tf.code, part)
            print(f"{tf.code}: {n} sham")
        print(f"Y1: {rebuild_yearly(session, args.symbol)} sham")


if __name__ == "__main__":
    main()
