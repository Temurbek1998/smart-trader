"""Bitta ish sikli: ma'lumot yig'ish -> demo savdolarni yangilash -> monitoring -> chuqur tahlil -> signal."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.analysis import claude_analyst as analyst
from app.analysis.signals import check
from app.analysis.snapshot import build_snapshot, monitor_view
from app.analysis.strategies import STRATEGIES
from app.config import settings
from app.data.collector import collect
from app.data.providers import get_provider
from app.data.store import load_candles
from app.db import Analysis, SessionLocal, Signal, init_db
from app.trading import paper

log = logging.getLogger(__name__)

# Monitoring nima desa ham, shuncha vaqtda bir marta chuqur tahlil qilinadi
MAX_DEEP_GAP = timedelta(hours=4)


def _last_deep(session) -> Analysis | None:
    return session.scalar(
        select(Analysis).where(Analysis.kind == "deep").order_by(Analysis.ts.desc()).limit(1)
    )


def run_cycle(force_deep: bool = False) -> dict:
    report: dict = {"time": datetime.now(timezone.utc).isoformat()}
    report["collected"] = collect()
    symbol = settings.symbol

    with SessionLocal() as session:
        recent = load_candles(session, symbol, "M1", limit=max(settings.monitor_every_min, 1))
        if not recent.empty:
            closed = paper.update_trades(session, symbol, recent["high"].max(), recent["low"].min())
            report["closed_trades"] = [t.id for t in closed]

        if not settings.anthropic_api_key:
            report["skipped"] = "ANTHROPIC_API_KEY yo'q"
            return report
        spent = analyst.spent_today(session)
        if spent >= settings.daily_cost_limit_usd:
            report["skipped"] = f"kunlik limit: ${spent:.2f}"
            return report

        snapshot = build_snapshot(session, symbol)
        last = _last_deep(session)
        due = last is None or datetime.now(timezone.utc) - last.ts.replace(tzinfo=timezone.utc) > MAX_DEEP_GAP
        if not (force_deep or due):
            decision, _ = analyst.monitor(session, monitor_view(snapshot), last.output if last else None)
            report["monitor"] = decision
            if not decision["analyze"]:
                return report

        report["signals"] = []
        for strategy in STRATEGIES:
            try:
                result, row = analyst.analyze(session, snapshot, strategy)
            except Exception as exc:
                log.exception("%s tahlili xato", strategy.key)
                report["signals"].append({"strategy": strategy.key, "error": str(exc)})
                continue
            published, agree, problems = check(result)
            sig = Signal(
                analysis_id=row.id, strategy=strategy.key, symbol=symbol, side=result["side"],
                entry=result["entry"] or None, stop_loss=result["stop_loss"] or None,
                take_profit=result["take_profit"] or None, confidence=result["confidence"],
                timeframes_agree=agree, published=published, reason=result["reason"],
            )
            session.add(sig)
            session.commit()
            entry = {"strategy": strategy.key, "side": sig.side, "published": published, "problems": problems}
            if published:
                trade = paper.open_trade(session, sig)
                entry["paper_trade"] = trade.id if trade else None
                if trade and settings.execute_on_mt5 and settings.data_provider == "mt5":
                    entry["mt5"] = get_provider().send_order(
                        symbol, sig.side, trade.qty, sig.stop_loss, sig.take_profit, f"ST {strategy.key}"
                    )
            report["signals"].append(entry)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--deep", action="store_true", help="monitoringsiz darhol chuqur tahlil")
    args = p.parse_args()
    init_db()
    print(run_cycle(force_deep=args.deep))
