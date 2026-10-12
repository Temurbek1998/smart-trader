"""Oltin bozori vaqti va asosiy darajalar. Aniq raqamlarni Python hisoblaydi, Claude faqat baholaydi."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy.orm import Session

from app.data.store import load_candles


def market_open(now: datetime) -> bool:
    """XAUUSD juma 21:00 UTC dan yakshanba 22:00 UTC gacha yopiq (taxminan, yozgi vaqtni hisobga olmasdan)."""
    wd, h = now.weekday(), now.hour
    if wd == 5:
        return False
    if wd == 4 and h >= 21:
        return False
    if wd == 6 and h < 22:
        return False
    return True


def session_name(now: datetime) -> str:
    h = now.hour
    if 12 <= h < 16:
        return "LONDON_NEWYORK_OVERLAP"
    if 7 <= h < 12:
        return "LONDON"
    if 16 <= h < 21:
        return "NEWYORK"
    return "ASIA"


def active_session(now: datetime) -> bool:
    """Likvidlik yuqori payt: London ochilishidan Nyu-York yopilishigacha."""
    return market_open(now) and 7 <= now.hour < 20


def key_levels(session: Session, symbol: str, now: datetime) -> dict:
    """Oldingi kun/hafta high-low va bugungi Osiyo sessiyasi oralig'i."""
    out: dict = {}
    r = lambda v: None if v is None or pd.isna(v) else round(float(v), 2)  # noqa: E731
    d1 = load_candles(session, symbol, "D1", limit=3)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    prev = d1[d1.index < today]
    if not prev.empty:
        out["prev_day_high"], out["prev_day_low"] = r(prev["high"].iloc[-1]), r(prev["low"].iloc[-1])
    w1 = load_candles(session, symbol, "W1", limit=3)
    week_start = today - timedelta(days=today.weekday())
    prevw = w1[w1.index < week_start - timedelta(days=1)]
    if not prevw.empty:
        out["prev_week_high"], out["prev_week_low"] = r(prevw["high"].iloc[-1]), r(prevw["low"].iloc[-1])
    m15 = load_candles(session, symbol, "M15", start=today, end=today + timedelta(hours=7) - timedelta(seconds=1))
    if not m15.empty:
        out["asia_range_high"], out["asia_range_low"] = r(m15["high"].max()), r(m15["low"].min())
    return out


def context(session: Session, symbol: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "utc_time": now.strftime("%Y-%m-%d %H:%M"),
        "weekday": now.strftime("%A"),
        "session": session_name(now),
        "market_open": market_open(now),
        "levels": key_levels(session, symbol, now),
    }
