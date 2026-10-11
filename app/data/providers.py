"""Narx manbalari.

MT5Provider asosiy manba: MetaTrader 5 terminalidan to'g'ridan-to'g'ri o'qiydi
(faqat Windows'da, terminal o'rnatilgan va brokerga kirilgan bo'lishi kerak).
TwelveDataProvider serverless (Vercel) uchun: REST API, Windows shart emas.
YahooProvider sinov uchun: kalitsiz, oltin fyuchersi (GC=F) narxi, intraday tarixi qisqa.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

import pandas as pd

from app.config import settings

COLUMNS = ["open", "high", "low", "close", "volume"]


class PriceProvider(Protocol):
    name: str

    def candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """UTC vaqt indeksli, COLUMNS ustunli DataFrame qaytaradi (eski -> yangi)."""

    def last_price(self, symbol: str) -> float: ...


class MT5Provider:
    name = "mt5"

    def __init__(self) -> None:
        import MetaTrader5 as mt5  # Windows-only paket

        self.mt5 = mt5
        kwargs = {}
        if settings.mt5_path:
            kwargs["path"] = settings.mt5_path
        if settings.mt5_login:
            kwargs.update(
                login=int(settings.mt5_login),
                password=settings.mt5_password,
                server=settings.mt5_server,
            )
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 ga ulanib bo'lmadi: {mt5.last_error()}")
        self._tf = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1,
            "MN1": mt5.TIMEFRAME_MN1,
        }

    def candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        self.mt5.symbol_select(symbol, True)
        rates = self.mt5.copy_rates_from_pos(symbol, self._tf[timeframe], 0, count)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"MT5 {symbol} {timeframe}: {self.mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df["volume"] = df["tick_volume"]
        return df.set_index("ts")[COLUMNS]

    def last_price(self, symbol: str) -> float:
        tick = self.mt5.symbol_info_tick(symbol)
        return (tick.bid + tick.ask) / 2

    def account(self) -> dict:
        info = self.mt5.account_info()
        return info._asdict() if info else {}

    def send_order(
        self, symbol: str, side: str, volume: float, sl: float, tp: float, comment: str
    ) -> dict:
        """Demo hisobda bozor buyurtmasini ochadi."""
        mt5 = self.mt5
        tick = mt5.symbol_info_tick(symbol)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if side == "BUY" else tick.bid,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 550055,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        return result._asdict() if result else {"error": str(mt5.last_error())}


class YahooProvider:
    """Sinov manbasi. XAUUSD o'rniga oltin fyuchersi GC=F ishlatiladi."""

    name = "yahoo"
    TICKERS = {"XAUUSD": "GC=F"}
    # (yahoo interval, yuklanadigan davr, qayta guruhlash qoidasi)
    MAP = {
        "M1": ("1m", "7d", None),
        "M5": ("5m", "60d", None),
        "M15": ("15m", "60d", None),
        "H1": ("1h", "730d", None),
        "H4": ("1h", "730d", "4h"),
        "D1": ("1d", "max", None),
        "W1": ("1wk", "max", None),
        "MN1": ("1mo", "max", None),
    }

    def _ticker(self, symbol: str) -> str:
        return self.TICKERS.get(symbol, symbol)

    def candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        import yfinance as yf

        interval, period, rule = self.MAP[timeframe]
        raw = yf.Ticker(self._ticker(symbol)).history(
            period=period, interval=interval, auto_adjust=False
        )
        if raw.empty:
            raise RuntimeError(f"Yahoo {symbol} {timeframe}: ma'lumot yo'q")
        df = raw.rename(columns=str.lower)[COLUMNS]
        df.index = pd.to_datetime(df.index, utc=True)
        df.index.name = "ts"
        if rule:
            df = resample(df, rule)
        return df.tail(count)

    def last_price(self, symbol: str) -> float:
        return float(self.candles(symbol, "M1", 1)["close"].iloc[-1])


class TwelveDataProvider:
    """Serverless (Vercel) uchun narx manbasi: Twelve Data REST API, XAU/USD.
    Bepul tarif: kuniga 800, daqiqasiga 8 so'rov."""

    name = "twelvedata"
    URL = "https://api.twelvedata.com/time_series"
    SYMBOLS = {"XAUUSD": "XAU/USD"}
    INTERVALS = {
        "M1": "1min", "M5": "5min", "M15": "15min", "H1": "1h",
        "H4": "4h", "D1": "1day", "W1": "1week", "MN1": "1month",
    }

    def __init__(self) -> None:
        import os

        self.api_key = os.getenv("TWELVEDATA_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("TWELVEDATA_API_KEY berilmagan")

    def candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        import httpx

        params = {
            "symbol": self.SYMBOLS.get(symbol, symbol),
            "interval": self.INTERVALS[timeframe],
            "outputsize": min(max(count, 1), 5000),
            "timezone": "UTC",
            "order": "asc",
            "apikey": self.api_key,
        }
        data = httpx.get(self.URL, params=params, timeout=30).json()
        if data.get("status") != "ok":
            raise RuntimeError(f"Twelve Data {symbol} {timeframe}: {data.get('message')}")
        df = pd.DataFrame(data["values"])
        df["ts"] = pd.to_datetime(df["datetime"], utc=True)
        for c in COLUMNS:
            df[c] = pd.to_numeric(df[c], errors="coerce") if c in df else 0.0
        return df.set_index("ts")[COLUMNS].fillna({"volume": 0.0})

    def last_price(self, symbol: str) -> float:
        return float(self.candles(symbol, "M1", 1)["close"].iloc[-1])


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open"])


_provider: PriceProvider | None = None


def get_provider() -> PriceProvider:
    global _provider
    if _provider is None:
        _provider = {
            "mt5": MT5Provider,
            "twelvedata": TwelveDataProvider,
        }.get(settings.data_provider, YahooProvider)()
    return _provider


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
