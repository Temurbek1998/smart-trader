"""Smart Trader qo'llaydigan 9 ta vaqt oralig'i."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Timeframe:
    code: str  # M1, H4, Y1 ...
    minutes: int  # taxminiy uzunlik, oylik va yillik uchun o'rtacha
    pandas_rule: str  # resample qoidasi
    # Claude'ga beriladigan oxirgi shamlar soni
    snapshot_bars: int
    # Birinchi yuklashda olinadigan shamlar soni
    history_bars: int


TIMEFRAMES: list[Timeframe] = [
    Timeframe("M1", 1, "1min", 60, 20_000),
    Timeframe("M5", 5, "5min", 60, 20_000),
    Timeframe("M15", 15, "15min", 64, 20_000),
    Timeframe("H1", 60, "1h", 72, 20_000),
    Timeframe("H4", 240, "4h", 60, 10_000),
    Timeframe("D1", 1440, "1D", 120, 5_000),
    Timeframe("W1", 10080, "W-SUN", 104, 1_000),
    Timeframe("MN1", 43200, "MS", 240, 400),
    # Yillik shamlar oylikdan hisoblanadi, provayderdan olinmaydi
    Timeframe("Y1", 525600, "YS", 30, 0),
]

BY_CODE = {tf.code: tf for tf in TIMEFRAMES}
FETCHED = [tf for tf in TIMEFRAMES if tf.code != "Y1"]
