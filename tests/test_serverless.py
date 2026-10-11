from datetime import timedelta

import pandas as pd
from fastapi.testclient import TestClient

from app.data import collector
from app.data.providers import TwelveDataProvider, now_utc
from app.data.store import upsert_candles
from app.db import SessionLocal
from app.web.main import app


class Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def test_twelvedata_parses_values(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "k")
    seen = {}

    def fake_get(url, params, timeout):
        seen.update(params)
        return Resp({"status": "ok", "values": [
            {"datetime": "2026-10-09 10:00:00", "open": "2650.1", "high": "2655", "low": "2649", "close": "2654.2"},
            {"datetime": "2026-10-09 11:00:00", "open": "2654.2", "high": "2660", "low": "2651", "close": "2658.0"},
        ]})

    monkeypatch.setattr("httpx.get", fake_get)
    df = TwelveDataProvider().candles("XAUUSD", "H1", 2)
    assert seen["symbol"] == "XAU/USD" and seen["interval"] == "1h"
    assert list(df["close"]) == [2654.2, 2658.0] and (df["volume"] == 0).all()
    assert str(df.index.tz) == "UTC"


def test_incremental_collect_skips_unfinished_bars(monkeypatch):
    calls = []

    class Fake:
        def candles(self, symbol, tf, count):
            calls.append((tf, count))
            ts = pd.date_range(now_utc().replace(second=0, microsecond=0) - timedelta(minutes=2), periods=2, freq="1min")
            return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0.0}, index=ts.rename("ts"))

    monkeypatch.setattr(collector, "get_provider", lambda: Fake())
    with SessionLocal() as s:
        recent = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [0.0]},
                              index=pd.DatetimeIndex([now_utc() - timedelta(minutes=10)], name="ts"))
        upsert_candles(s, "XAUUSD", "H1", recent)  # 10 daqiqalik H1 sham: hali yopilmagan
    collector.collect()
    fetched = {tf for tf, _ in calls}
    assert "M1" in fetched and "H1" not in fetched and "D1" in fetched  # D1 bazada yo'q edi


def test_cron_requires_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    monkeypatch.setenv("WEB_PASSWORD", "pw")
    ran = []
    monkeypatch.setattr("app.web.main.run_cycle", lambda force_deep=False: ran.append(force_deep) or {"ok": True})
    with TestClient(app) as c:
        assert c.get("/api/cron").status_code == 401
        assert c.get("/api/cron", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/cron", headers={"Authorization": "Bearer s3cret"}).json() == {"ok": True}
        assert c.get("/api/cron?key=s3cret").json() == {"ok": True}
        assert c.get("/api/cron?key=wrong").status_code == 401
    assert ran == [False]
