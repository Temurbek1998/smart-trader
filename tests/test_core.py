from types import SimpleNamespace

import pandas as pd

from app.analysis import claude_analyst as analyst
from app.analysis.signals import check
from app.analysis.snapshot import build_snapshot
from app.analysis.strategies import BY_KEY
from app.data.providers import resample
from app.data.store import load_candles, rebuild_yearly, upsert_candles
from app.db import SessionLocal, Signal
from app.indicators import add_all, rsi, summarize
from app.trading import paper
from tests.conftest import make_candles

GOOD = {
    "side": "BUY", "entry": 2400.0, "stop_loss": 2390.0, "take_profit": 2420.0, "confidence": 0.8,
    "higher_tf_bias": "UP", "lower_tf_bias": "UP", "trade_timeframe": "H1", "key_levels": [2390, 2420],
    "reason": "test",
}


def test_indicators_shapes_and_ranges():
    df = make_candles()
    ind = add_all(df)
    assert {"ema_20", "rsi_14", "macd_hist", "atr_14", "bb_upper"} <= set(ind.columns)
    assert ind["rsi_14"].between(0, 100).all()
    up = pd.Series(range(1, 50), dtype=float)
    assert rsi(up).iloc[-1] == 100
    s = summarize(df)
    assert s["trend"] in {"UP", "DOWN", "FLAT"} and s["bars"] == 600


def test_upsert_is_idempotent_and_yearly_built_from_monthly():
    monthly = resample(make_candles(n=3 * 365, freq="1D"), "MS")
    with SessionLocal() as s:
        upsert_candles(s, "XAUUSD", "MN1", monthly)
        upsert_candles(s, "XAUUSD", "MN1", monthly)
        assert len(load_candles(s, "XAUUSD", "MN1")) == len(monthly)
        assert rebuild_yearly(s, "XAUUSD") == 3
        y = load_candles(s, "XAUUSD", "Y1")
        assert y["high"].iloc[0] == monthly.loc["2024"]["high"].max()


def test_signal_rule():
    assert check(GOOD, 0.7)[0] is True
    assert check({**GOOD, "confidence": 0.6}, 0.7)[0] is False
    assert check({**GOOD, "lower_tf_bias": "DOWN"}, 0.7)[0] is False
    assert check({**GOOD, "take_profit": 2405.0}, 0.7)[0] is False  # risk/foyda 1:0.5
    assert check({**GOOD, "stop_loss": 2410.0}, 0.7)[0] is False  # tartib noto'g'ri
    sell = {**GOOD, "side": "SELL", "stop_loss": 2410.0, "take_profit": 2380.0,
            "higher_tf_bias": "DOWN", "lower_tf_bias": "DOWN"}
    assert check(sell, 0.7)[0] is True
    assert check({**GOOD, "side": "HOLD"}, 0.7)[0] is False


def test_paper_trade_sizing_and_close():
    with SessionLocal() as s:
        sig = Signal(analysis_id=0, strategy="trend", symbol="XAUUSD", side="BUY", entry=2400.0,
                     stop_loss=2390.0, take_profit=2420.0, confidence=0.8, published=True)
        s.add(sig)
        s.commit()
        t = paper.open_trade(s, sig)
        # 10 000 * 1% = 100 USD xavf, 10 USD * 100 untsiya = 1000 USD/lot -> 0.1 lot
        assert t.qty == 0.1
        assert paper.open_trade(s, sig) is None  # bitta strategiyada bitta ochiq savdo
        assert paper.update_trades(s, "XAUUSD", high=2415, low=2395) == []
        closed = paper.update_trades(s, "XAUUSD", high=2421, low=2401)
        assert closed[0].status == "TP" and closed[0].pnl == 200.0
        assert paper.balance(s) == 10200.0
        assert paper.stats(s)[0]["win_rate"] == 100.0


class FakeMessages:
    """Birinchi javobda query_history chaqiradi, ikkinchisida signal JSON qaytaradi."""

    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        usage = SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        if len(self.calls) == 1:
            block = SimpleNamespace(type="tool_use", id="tu1", name="query_history",
                                    input={"timeframe": "H1", "start": "2024-01-02", "end": "2024-01-05"})
            return SimpleNamespace(stop_reason="tool_use", content=[block], usage=usage, model=kw["model"])
        import json
        return SimpleNamespace(stop_reason="end_turn", usage=usage, model=kw["model"],
                               content=[SimpleNamespace(type="text", text=json.dumps(GOOD))])


def test_analyze_tool_loop(monkeypatch):
    fake = FakeMessages()
    monkeypatch.setattr(analyst, "_client", SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    with SessionLocal() as s:
        upsert_candles(s, "XAUUSD", "H1", make_candles())
        snap = build_snapshot(s, "XAUUSD")
        assert "H1" in snap["timeframes"] and snap["price"] is not None
        result, row = analyst.analyze(s, snap, BY_KEY["macro"])
    assert result["side"] == "BUY" and row.kind == "deep" and row.input_tokens == 2000
    first = fake.calls[0]
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert "tool_choice" not in first
    assert any(t.get("type") == "web_search_20260209" for t in first["tools"])
    tool_result = fake.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and "bars_in_range" in tool_result["content"]
    assert round(row.cost_usd, 4) == round(2 * (1000 * 4 + 200 * 20) / 1e6, 4)
