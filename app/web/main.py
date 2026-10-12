"""Web panel: signallar, demo savdolar, grafik va strategiyalar reytingi."""

from __future__ import annotations

import logging
import os
import secrets
import threading
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.analysis.claude_analyst import spent_today
from app.analysis.strategies import STRATEGIES
from app.config import settings
from app.data.store import load_candles
from app.db import AnalysisRequest, PaperTrade, SessionLocal, Signal, engine, init_db, utcnow
from app.engine import run_cycle
from app.timeframes import BY_CODE
from app.trading import paper

log = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
security = HTTPBasic(auto_error=False)
_cycle_lock = threading.Lock()


def auth(request: Request, creds: HTTPBasicCredentials | None = Depends(security)) -> None:
    if request.url.path == "/api/cron":  # o'z tekshiruvi bor (CRON_SECRET)
        return
    password = os.getenv("WEB_PASSWORD", "")
    if not password:
        return
    ok = creds is not None and secrets.compare_digest(
        creds.username, os.getenv("WEB_USER", "admin")
    ) and secrets.compare_digest(creds.password, password)
    if not ok:
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


def _safe_cycle(force_deep: bool = False) -> None:
    if not _cycle_lock.acquire(blocking=False):
        log.info("Oldingi sikl hali tugamagan")
        return
    try:
        log.info("Sikl: %s", run_cycle(force_deep=force_deep))
    except Exception:
        log.exception("Sikl xatosi")
    finally:
        _cycle_lock.release()


def scheduler_enabled() -> bool:
    """Vercel'da fon jarayoni yo'q: u yerda tahlilni alohida worker bajaradi."""
    return os.getenv("RUN_SCHEDULER", "true").lower() == "true" and not os.getenv("VERCEL")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        init_db()
    except Exception:
        # Baza vaqtincha mavjud bo'lmasa ham sayt ochilsin; xato logda ko'rinadi
        log.exception("Bazani tayyorlab bo'lmadi")
    scheduler = None
    if scheduler_enabled():
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(_safe_cycle, "interval", minutes=settings.monitor_every_min, max_instances=1)
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Smart Trader", lifespan=lifespan, dependencies=[Depends(auth)])


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html",
        {"symbol": settings.symbol, "timeframes": list(BY_CODE), "titles": {x.key: x.title for x in STRATEGIES}},
    )


@app.get("/api/candles")
def candles(tf: str = "H1", limit: int = 300):
    if tf not in BY_CODE:
        raise HTTPException(400, "noma'lum vaqt oralig'i")
    with SessionLocal() as s:
        df = load_candles(s, settings.symbol, tf, limit=min(limit, 5000))
    return [
        {"time": int(ts.timestamp()), "open": r.open, "high": r.high, "low": r.low, "close": r.close}
        for ts, r in df.iterrows()
    ]


@app.get("/api/signals")
def signals(limit: int = 50, published_only: bool = False):
    with SessionLocal() as s:
        q = select(Signal).order_by(Signal.ts.desc()).limit(min(limit, 500))
        if published_only:
            q = q.where(Signal.published.is_(True))
        return [
            {
                "id": x.id, "ts": x.ts.isoformat(), "strategy": x.strategy, "side": x.side,
                "entry": x.entry, "stop_loss": x.stop_loss, "take_profit": x.take_profit,
                "confidence": x.confidence, "published": x.published, "reason": x.reason,
            }
            for x in s.scalars(q)
        ]


@app.get("/api/trades")
def trades(limit: int = 100):
    with SessionLocal() as s:
        q = select(PaperTrade).order_by(PaperTrade.opened_at.desc()).limit(min(limit, 500))
        return [
            {
                "id": t.id, "strategy": t.strategy, "side": t.side, "qty": t.qty,
                "entry": t.entry_price, "sl": t.stop_loss, "tp": t.take_profit,
                "opened_at": t.opened_at.isoformat(),
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
                "exit": t.exit_price, "pnl": t.pnl, "status": t.status,
            }
            for t in s.scalars(q)
        ]


@app.get("/api/stats")
def stats():
    with SessionLocal() as s:
        per_strategy = paper.stats(s)
        closed = sum(r["trades"] for r in per_strategy)
        wins = sum(r["wins"] for r in per_strategy)
        return {
            "symbol": settings.symbol,
            "provider": settings.data_provider,
            "database": engine.dialect.name,
            "balance": round(paper.balance(s), 2),
            "start_balance": settings.paper_balance,
            "closed_trades": closed,
            "win_rate": round(100 * wins / closed, 1) if closed else None,
            "claude_cost_today": round(spent_today(s), 4),
            "daily_cost_limit": settings.daily_cost_limit_usd,
            "strategies": per_strategy,
        }


@app.get("/api/cron")
def cron(request: Request):
    """Vercel Cron har 5 daqiqada chaqiradi. Vercel `Authorization: Bearer <CRON_SECRET>` yuboradi."""
    secret = os.getenv("CRON_SECRET", "").strip()
    # Sarlavha (`Authorization: Bearer <kod>`) yoki URL'dagi `?key=<kod>` qabul qilinadi
    given = request.headers.get("authorization", "").strip()
    if given.lower().startswith("bearer "):
        given = given[7:].strip()
    given = given or request.query_params.get("key", "").strip()
    if not secret or not secrets.compare_digest(given, secret):
        raise HTTPException(401, "CRON_SECRET mos kelmadi" if secret else "Vercel'da CRON_SECRET yo'q")
    with SessionLocal() as s:
        pending = s.scalars(select(AnalysisRequest).where(AnalysisRequest.done_at.is_(None))).all()
        for r in pending:
            r.done_at = utcnow()
        s.commit()
    try:
        return run_cycle(force_deep=bool(pending))
    except Exception as exc:  # sababini cron javobida ko'rsatamiz, "Internal Server Error" o'rniga
        log.exception("cron sikli xato")
        tb = traceback.extract_tb(exc.__traceback__)[-3:]
        return JSONResponse(
            {"error": f"{type(exc).__name__}: {exc}"[:2000], "where": [f"{f.filename.split('/app/')[-1]}:{f.lineno} {f.name}" for f in tb]},
            status_code=500,
        )


@app.post("/api/analyze")
def analyze_now():
    if not scheduler_enabled():
        with SessionLocal() as s:
            pending = s.scalar(select(AnalysisRequest).where(AnalysisRequest.done_at.is_(None)).limit(1))
            if pending:
                return {"started": False, "message": "So'rov navbatda"}
            s.add(AnalysisRequest())
            s.commit()
        return {"started": True, "queued": True}
    if _cycle_lock.locked():
        return {"started": False, "message": "Tahlil allaqachon ketmoqda"}
    threading.Thread(target=_safe_cycle, kwargs={"force_deep": True}, daemon=True).start()
    return {"started": True}
