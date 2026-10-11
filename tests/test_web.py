from fastapi.testclient import TestClient

from app.data.store import upsert_candles
from app.db import SessionLocal
from app.web.main import app
from tests.conftest import make_candles


def test_dashboard_and_api():
    with SessionLocal() as s:
        upsert_candles(s, "XAUUSD", "H1", make_candles(n=50))
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
        assert len(c.get("/api/candles?tf=H1").json()) == 50
        assert c.get("/api/candles?tf=X9").status_code == 400
        st = c.get("/api/stats").json()
        assert st["balance"] == 10000 and st["closed_trades"] == 0
        assert c.get("/api/signals").json() == []


def test_password(monkeypatch):
    monkeypatch.setenv("WEB_PASSWORD", "secret")
    with TestClient(app) as c:
        assert c.get("/api/stats").status_code == 401
        assert c.get("/api/stats", auth=("admin", "secret")).status_code == 200
