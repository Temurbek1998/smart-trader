"""Demo (paper) savdo dvigateli. Haqiqiy pul ishlatilmaydi."""

from __future__ import annotations

import logging

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import PaperTrade, Signal, utcnow

log = logging.getLogger(__name__)

# 1 lot XAUUSD = 100 untsiya
CONTRACT_SIZE = 100


def balance(session: Session) -> float:
    realized = session.scalar(select(func.sum(PaperTrade.pnl)).where(PaperTrade.status != "OPEN"))
    return settings.paper_balance + float(realized or 0)


def position_size(bal: float, entry: float, sl: float) -> float:
    """Har savdoda balansning RISK_PER_TRADE qismini xavf ostiga qo'yadi. Natija lotda, 0.01 qadam."""
    risk_usd = bal * settings.risk_per_trade
    per_lot = abs(entry - sl) * CONTRACT_SIZE
    if per_lot <= 0:
        return 0.0
    return max(0.01, round(risk_usd / per_lot, 2))


def open_trade(session: Session, signal: Signal) -> PaperTrade | None:
    already = session.scalar(
        select(PaperTrade).where(
            PaperTrade.strategy == signal.strategy,
            PaperTrade.symbol == signal.symbol,
            PaperTrade.status == "OPEN",
        )
    )
    if already:
        log.info("%s strategiyasida ochiq savdo bor, yangisi ochilmaydi", signal.strategy)
        return None
    qty = position_size(balance(session), signal.entry, signal.stop_loss)
    trade = PaperTrade(
        signal_id=signal.id, strategy=signal.strategy, symbol=signal.symbol, side=signal.side,
        qty=qty, entry_price=signal.entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
    )
    session.add(trade)
    session.commit()
    return trade


def pnl(trade: PaperTrade, price: float) -> float:
    direction = 1 if trade.side == "BUY" else -1
    return round((price - trade.entry_price) * direction * trade.qty * CONTRACT_SIZE, 2)


def update_trades(session: Session, symbol: str, high: float, low: float) -> list[PaperTrade]:
    """Oxirgi sham high/low bo'yicha stop-loss yoki take-profit tegdimi tekshiradi.
    Ikkalasi bitta shamda tegsa, ehtiyotkorlik uchun stop-loss hisoblanadi."""
    closed = []
    for t in session.scalars(
        select(PaperTrade).where(PaperTrade.symbol == symbol, PaperTrade.status == "OPEN")
    ):
        if t.side == "BUY":
            hit_sl, hit_tp = low <= t.stop_loss, high >= t.take_profit
        else:
            hit_sl, hit_tp = high >= t.stop_loss, low <= t.take_profit
        if not (hit_sl or hit_tp):
            continue
        t.status = "SL" if hit_sl else "TP"
        t.exit_price = t.stop_loss if hit_sl else t.take_profit
        t.pnl = pnl(t, t.exit_price)
        t.closed_at = utcnow()
        closed.append(t)
    session.commit()
    return closed


def stats(session: Session) -> list[dict]:
    rows = session.execute(
        select(
            PaperTrade.strategy,
            func.count(),
            func.sum(PaperTrade.pnl),
            func.sum(case((PaperTrade.status == "TP", 1), else_=0)),
        )
        .where(PaperTrade.status != "OPEN")
        .group_by(PaperTrade.strategy)
    ).all()
    out = []
    for strategy, n, total, wins in rows:
        out.append(
            {
                "strategy": strategy,
                "trades": n,
                "wins": int(wins or 0),
                "win_rate": round(100 * (wins or 0) / n, 1) if n else 0,
                "pnl": round(float(total or 0), 2),
            }
        )
    return sorted(out, key=lambda r: r["pnl"], reverse=True)
