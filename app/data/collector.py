"""Provayderdan barcha vaqt oraliqlarini yuklab bazaga yozadi."""

from __future__ import annotations

import logging

from app.config import settings
from app.data.providers import get_provider
from app.data.store import rebuild_yearly, upsert_candles
from app.db import SessionLocal
from app.timeframes import FETCHED

log = logging.getLogger(__name__)


def collect(full_history: bool = False, timeframes: list[str] | None = None) -> dict[str, int]:
    """full_history=True bo'lsa, har vaqt oralig'i uchun uzun tarix yuklanadi."""
    provider = get_provider()
    counts: dict[str, int] = {}
    with SessionLocal() as session:
        for tf in FETCHED:
            if timeframes and tf.code not in timeframes:
                continue
            count = tf.history_bars if full_history else max(tf.snapshot_bars, 10)
            try:
                df = provider.candles(settings.symbol, tf.code, count)
                counts[tf.code] = upsert_candles(session, settings.symbol, tf.code, df)
            except Exception as exc:  # bitta vaqt oralig'i xatosi qolganini to'xtatmasin
                log.warning("%s yuklanmadi: %s", tf.code, exc)
                counts[tf.code] = 0
        counts["Y1"] = rebuild_yearly(session, settings.symbol)
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app.db import init_db

    init_db()
    print(collect(full_history=True))
