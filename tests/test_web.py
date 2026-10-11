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


def test_analyze_queues_request_when_no_scheduler(monkeypatch):
    from sqlalchemy import select

    from app.db import AnalysisRequest
    from app.worker import check_requests

    monkeypatch.setenv("VERCEL", "1")
    ran = []
    monkeypatch.setattr("app.worker.cycle", lambda force_deep=False: ran.append(force_deep))
    with TestClient(app) as c:
        assert c.post("/api/analyze").json() == {"started": True, "queued": True}
        assert c.post("/api/analyze").json()["started"] is False  # bittadan ortiq navbat yo'q
    check_requests()
    assert ran == [True]
    with SessionLocal() as s:
        assert s.scalar(select(AnalysisRequest)).done_at is not None


def test_neon_url_is_normalized(monkeypatch):
    from app.config import _db_url

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-x.neon.tech/db?sslmode=require")
    assert _db_url() == "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require"
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    assert _db_url().startswith("postgresql+psycopg://")
