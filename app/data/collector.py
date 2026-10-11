"""Provayderdan barcha vaqt oraliqlarini yuklab bazaga yozadi."""

from __future__ import annotations

import logging

from app.config import settings
from app.data.store import last_ts, rebuild_yearly, upsert_candles
from app.db import SessionLocal
from app.data.providers import get_provider, now_utc
from app.timeframes import FETCHED

log = logging.getLogger(__name__)


def collect(
    full_history: bool = False, timeframes: list[str] | None = None, errors: dict[str, str] | None = None
) -> dict[str, int]:
    """full_history=True bo'lsa, har vaqt oralig'i uchun uzun tarix yuklanadi.
    errors berilsa, yuklanmagan vaqt oraliqlari sababi shunga yoziladi."""
    errors = {} if errors is None else errors
    counts: dict[str, int] = {}
    try:
        provider = get_provider()
    except Exception as exc:
        errors["provider"] = str(exc)
        return counts
    with SessionLocal() as session:
        for tf in FETCHED:
            if timeframes and tf.code not in timeframes:
                continue
            if full_history:
                count = tf.history_bars
            else:
                last = last_ts(session, settings.symbol, tf.code)
                if last is None:
                    count = max(tf.snapshot_bars + 200, 300)
                else:
                    age_min = (now_utc() - last).total_seconds() / 60
                    # Yangi sham hali yopilmagan bo'lsa so'rov yubormaymiz (API limitini tejash).
                    # M1 har siklda yangilanadi: demo savdolar stop/take-profit tekshiruvi shunga bog'liq.
                    if tf.code != "M1" and age_min < tf.minutes:
                        counts[tf.code] = 0
                        continue
                    count = min(int(age_min / tf.minutes) + 3, 5000)
            try:
                df = provider.candles(settings.symbol, tf.code, count)
                counts[tf.code] = upsert_candles(session, settings.symbol, tf.code, df)
            except Exception as exc:  # bitta vaqt oralig'i xatosi qolganini to'xtatmasin
                log.warning("%s yuklanmadi: %s", tf.code, exc)
                errors[tf.code] = str(exc)
                counts[tf.code] = 0
        counts["Y1"] = rebuild_yearly(session, settings.symbol)
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app.db import init_db

    init_db()
    print(collect(full_history=True))
