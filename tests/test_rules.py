from datetime import datetime, timezone
from types import SimpleNamespace

from app import engine
from app.analysis.market import active_session, market_open, session_name
from app.data.store import upsert_candles
from app.db import SessionLocal
from conftest import make_candles

BUY = {"side": "BUY", "entry": 2400, "stop_loss": 2390, "take_profit": 2430, "confidence": 0.8,
       "higher_tf_bias": "UP", "lower_tf_bias": "UP", "trade_timeframe": "H1", "key_levels": [],
       "conditions_met": ["T1"], "high_impact_news_within_60min": False, "reason": "x"}
HOLD = {**BUY, "side": "HOLD", "entry": 0, "stop_loss": 0, "take_profit": 0}


def _run(monkeypatch, answers: dict) -> dict:
    def fake_analyze(session, snapshot, strategy):
        from app.db import Analysis
        row = Analysis(symbol="XAUUSD", kind="deep", strategy=strategy.key, model="m",
                       input_snapshot={}, output={}, cost_usd=0)
        session.add(row)
        session.commit()
        return answers[strategy.key], row

    monkeypatch.setattr(engine, "collect", lambda errors=None: {})
    monkeypatch.setattr(engine.analyst, "analyze", fake_analyze)
    monkeypatch.setattr(engine, "market_open", lambda now: True)
    with SessionLocal() as s:
        upsert_candles(s, "XAUUSD", "H1", make_candles())
    report = engine.run_cycle(force_deep=True)
    return {r["strategy"]: r for r in report["signals"]}


def test_single_strategy_is_not_enough(monkeypatch):
    out = _run(monkeypatch, {"trend": BUY, "breakout": HOLD, "mean_reversion": HOLD, "macro": HOLD})
    assert out["trend"]["published"] is False
    assert any("kamida 2" in p for p in out["trend"]["problems"])


def test_two_agreeing_strategies_publish(monkeypatch):
    out = _run(monkeypatch, {"trend": BUY, "breakout": BUY, "mean_reversion": HOLD, "macro": HOLD})
    assert out["trend"]["published"] and out["breakout"]["published"]


def test_news_blocks_everything(monkeypatch):
    news = {**HOLD, "high_impact_news_within_60min": True}
    out = _run(monkeypatch, {"trend": BUY, "breakout": BUY, "mean_reversion": BUY, "macro": news})
    assert not any(r["published"] for r in out.values())
    assert any("yangilik" in p for p in out["trend"]["problems"])


def test_low_risk_reward_rejected(monkeypatch):
    weak = {**BUY, "take_profit": 2415}  # 1:1.5
    out = _run(monkeypatch, {"trend": weak, "breakout": weak, "mean_reversion": HOLD, "macro": HOLD})
    assert out["trend"]["published"] is False


def test_market_hours():
    sat = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    mon_london = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
    assert not market_open(sat)
    assert market_open(mon_london) and active_session(mon_london)
    assert session_name(datetime(2026, 10, 12, 13, tzinfo=timezone.utc)) == "LONDON_NEWYORK_OVERLAP"
    assert not market_open(datetime(2026, 10, 11, 21, tzinfo=timezone.utc))
    assert market_open(datetime(2026, 10, 11, 22, 30, tzinfo=timezone.utc))
