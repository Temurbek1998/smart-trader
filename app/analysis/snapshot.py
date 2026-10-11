"""Bozor holatini Claude uchun ixcham JSON'ga yig'ish."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.store import load_candles
from app.db import PaperTrade
from app.indicators import summarize
from app.timeframes import TIMEFRAMES

# Har vaqt oralig'idan Claude'ga to'liq ko'rsatiladigan oxirgi shamlar soni
RAW_BARS = {"M1": 30, "M5": 36, "M15": 32, "H1": 48, "H4": 42, "D1": 60, "W1": 52, "MN1": 120, "Y1": 30}


def _bars(df) -> list[list]:
    return [
        [ts.strftime("%Y-%m-%d %H:%M"), round(r.open, 2), round(r.high, 2), round(r.low, 2), round(r.close, 2)]
        for ts, r in df.iterrows()
    ]


def build_snapshot(session: Session, symbol: str) -> dict:
    frames = {}
    for tf in TIMEFRAMES:
        df = load_candles(session, symbol, tf.code, limit=tf.snapshot_bars + 200)
        if df.empty:
            continue
        frames[tf.code] = {
            "summary": summarize(df.tail(max(tf.snapshot_bars, 210))),
            "candles_ohlc": _bars(df.tail(RAW_BARS[tf.code])),
        }
    open_trades = session.scalars(
        select(PaperTrade).where(PaperTrade.symbol == symbol, PaperTrade.status == "OPEN")
    ).all()
    price = None
    for code in ("M1", "M5", "M15", "H1"):
        if code in frames:
            price = frames[code]["summary"].get("close")
            break
    return {
        "symbol": symbol,
        "price": price,
        "timeframes": frames,
        "open_paper_trades": [
            {"side": t.side, "entry": t.entry_price, "sl": t.stop_loss, "tp": t.take_profit, "strategy": t.strategy}
            for t in open_trades
        ],
    }


def monitor_view(snapshot: dict) -> dict:
    """Haiku uchun juda qisqa ko'rinish: faqat xulosalar, shamlarsiz."""
    return {
        "symbol": snapshot["symbol"],
        "price": snapshot["price"],
        "summaries": {k: v["summary"] for k, v in snapshot["timeframes"].items() if k in ("M5", "M15", "H1", "H4", "D1")},
    }
