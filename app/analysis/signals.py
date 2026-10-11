"""Ishonchli signal qoidasi: Claude javobi faqat shu tekshiruvlardan o'tsa e'lon qilinadi."""

from __future__ import annotations

from app.config import settings

MIN_RISK_REWARD = 1.5


def check(result: dict, min_confidence: float | None = None) -> tuple[bool, bool, list[str]]:
    """(published, timeframes_agree, sabablar) qaytaradi."""
    min_conf = settings.min_confidence if min_confidence is None else min_confidence
    side = result["side"]
    problems: list[str] = []
    want = {"BUY": "UP", "SELL": "DOWN"}.get(side)
    agree = want is not None and result["higher_tf_bias"] == want and result["lower_tf_bias"] == want

    if side == "HOLD":
        return False, False, ["HOLD"]
    if not agree:
        problems.append("katta va kichik vaqt oraliqlari bir yo'nalishda emas")
    if result["confidence"] < min_conf:
        problems.append(f"ishonch {result['confidence']:.2f} < {min_conf:.2f}")

    entry, sl, tp = result["entry"], result["stop_loss"], result["take_profit"]
    ordered = sl < entry < tp if side == "BUY" else tp < entry < sl
    if not ordered:
        problems.append("stop-loss / take-profit tartibi noto'g'ri")
    else:
        rr = abs(tp - entry) / abs(entry - sl)
        if rr < MIN_RISK_REWARD:
            problems.append(f"risk/foyda 1:{rr:.2f} < 1:{MIN_RISK_REWARD}")
    return not problems, agree, problems
