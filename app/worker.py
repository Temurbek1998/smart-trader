"""Doimiy ishlovchi jarayon: ma'lumot yig'adi, Claude bilan tahlil qiladi, demo savdolarni yuritadi.

Web panel Vercel'da bo'lganda shu jarayon MT5 o'rnatilgan Windows kompyuter yoki VPS'da ishlaydi
va bir xil Neon bazaga yozadi:
    python -m app.worker
"""

from __future__ import annotations

import logging
import threading

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from app.config import settings
from app.db import AnalysisRequest, SessionLocal, init_db, utcnow
from app.engine import run_cycle

log = logging.getLogger(__name__)
_lock = threading.Lock()


def cycle(force_deep: bool = False) -> None:
    if not _lock.acquire(blocking=False):
        return
    try:
        log.info("Sikl: %s", run_cycle(force_deep=force_deep))
    except Exception:
        log.exception("Sikl xatosi")
    finally:
        _lock.release()


def check_requests() -> None:
    """Web paneldan kelgan "Hozir tahlil qilish" so'rovlarini bajaradi."""
    with SessionLocal() as s:
        pending = s.scalars(select(AnalysisRequest).where(AnalysisRequest.done_at.is_(None))).all()
        if not pending:
            return
        for r in pending:
            r.done_at = utcnow()
        s.commit()
    cycle(force_deep=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(cycle, "interval", minutes=settings.monitor_every_min, max_instances=1, next_run_time=utcnow())
    scheduler.add_job(check_requests, "interval", seconds=30, max_instances=1)
    log.info("Worker ishga tushdi: har %s daqiqada sikl", settings.monitor_every_min)
    scheduler.start()


if __name__ == "__main__":
    main()
