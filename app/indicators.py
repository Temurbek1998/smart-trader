"""Texnik indikatorlar. Aniq hisob-kitobni Python qiladi, xulosani Claude chiqaradi."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Trend kuchi: 25 dan yuqori kuchli trend, 20 dan past yon harakat (range)."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = atr(df, 1)
    atr_n = tr.ewm(alpha=1 / n, adjust=False).mean().replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_n
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_n
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["close"]
    for n in (20, 50, 200):
        out[f"ema_{n}"] = ema(c, n)
    out["rsi_14"] = rsi(c)
    out = out.join(macd(c))
    out["atr_14"] = atr(out)
    out["adx_14"] = adx(out)
    mid = c.rolling(20).mean()
    std = c.rolling(20).std()
    out["bb_upper"] = mid + 2 * std
    out["bb_lower"] = mid - 2 * std
    return out


def trend(row: pd.Series) -> str:
    if row["close"] > row["ema_20"] > row["ema_50"]:
        return "UP"
    if row["close"] < row["ema_20"] < row["ema_50"]:
        return "DOWN"
    return "FLAT"


def summarize(df: pd.DataFrame) -> dict:
    """Bitta vaqt oralig'ining qisqa raqamli xulosasi (Claude'ga yuboriladi)."""
    if len(df) < 2:
        return {"bars": len(df)}
    ind = add_all(df)
    last = ind.iloc[-1]
    r = lambda v: None if pd.isna(v) else round(float(v), 2)  # noqa: E731
    return {
        "bars": len(df),
        "last_time": df.index[-1].isoformat(),
        "close": r(last["close"]),
        "change_pct": r((last["close"] / ind["close"].iloc[0] - 1) * 100),
        "trend": trend(last),
        "ema_20": r(last["ema_20"]),
        "ema_50": r(last["ema_50"]),
        "ema_200": r(last["ema_200"]) if len(df) >= 200 else None,
        "rsi_14": r(last["rsi_14"]),
        "macd_hist": r(last["macd_hist"]),
        "atr_14": r(last["atr_14"]),
        "adx_14": r(last["adx_14"]),
        "bb_upper": r(last["bb_upper"]),
        "bb_lower": r(last["bb_lower"]),
        "range_high": r(ind["high"].max()),
        "range_low": r(ind["low"].min()),
    }
