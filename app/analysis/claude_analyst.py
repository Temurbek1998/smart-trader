"""Barcha tahlil va signal qarorlari Claude API orqali.

- monitor(): Haiku arzon tekshiradi, chuqur tahlil kerakmi.
- analyze(): Opus bitta strategiya bo'yicha chuqur tahlil qiladi, kerak bo'lsa
  bazadagi butun arxivdan `query_history` asbobi bilan qo'shimcha davr so'raydi,
  javobni qat'iy JSON sxema bo'yicha qaytaradi.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import anthropic
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.strategies import Strategy
from app.config import settings
from app.data.store import load_candles
from app.db import Analysis
from app.indicators import summarize
from app.timeframes import BY_CODE

log = logging.getLogger(__name__)

# USD / 1M token: (input, output)
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}

FALLBACK_BETA = "server-side-fallback-2026-07-01"

BASE_SYSTEM = """Sen oltin (XAUUSD) bozorining tajribali tahlilchisisan. Vazifang: berilgan bozor ma'lumotlarini \
chuqur tahlil qilib, faqat ishonchli savdo signalini berish.

Ma'lumot: 9 ta vaqt oralig'i (M1, M5, M15, H1, H4, D1, W1, MN1, Y1). Har biri uchun indikatorlar xulosasi va \
oxirgi shamlar [vaqt, open, high, low, close] ko'rinishida. Bazada 10 yildan ortiq tarix bor: qo'shimcha davr \
kerak bo'lsa (masalan, shunga o'xshash tarixiy holatni ko'rish uchun) `query_history` asbobidan foydalan.

Qoidalar:
- Avval katta vaqt oraliqlaridan (Y1, MN1, W1, D1) umumiy yo'nalishni aniqla, keyin H4/H1 da tuzilmani, \
oxirida M15/M5/M1 da kirish nuqtasini.
- higher_tf_bias = D1 va H4 umumiy yo'nalishi; lower_tf_bias = H1 va M15 yo'nalishi.
- Ishonching past bo'lsa yoki vaqt oraliqlari bir-biriga zid bo'lsa, HOLD ber. Noto'g'ri signaldan HOLD yaxshiroq.
- BUY uchun stop_loss < entry < take_profit, SELL uchun take_profit < entry < stop_loss. Risk/foyda nisbati \
kamida 1:2 bo'lsin. HOLD bo'lsa entry, stop_loss, take_profit = 0.
- Strategiyaning har bir majburiy sharti bajarilganini snapshot'dagi aniq raqam bilan isbotla. Taxmin bilan shart \
bajarildi dema. market bo'limida vaqt, sessiya va asosiy darajalar tayyor hisoblangan.
- high_impact_news_within_60min: web qidiruvsiz strategiyalarda false qo'y (buni macro strategiyasi tekshiradi).
- confidence 0 dan 1 gacha: tarixda shunday holatlarda bu signal necha foiz to'g'ri chiqqanini halol baholang.
- reason maydonini o'zbek tilida, 3-6 gapda yoz: asosiy dalillar va signalni bekor qiladigan narx darajasi.
"""

SIGNAL_SCHEMA = {
    "type": "object",
    "properties": {
        "side": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
        "entry": {"type": "number"},
        "stop_loss": {"type": "number"},
        "take_profit": {"type": "number"},
        "confidence": {"type": "number"},
        "higher_tf_bias": {"type": "string", "enum": ["UP", "DOWN", "FLAT"]},
        "lower_tf_bias": {"type": "string", "enum": ["UP", "DOWN", "FLAT"]},
        "trade_timeframe": {"type": "string", "enum": ["M15", "H1", "H4", "D1"]},
        "key_levels": {"type": "array", "items": {"type": "number"}},
        "conditions_met": {"type": "array", "items": {"type": "string"}},
        "high_impact_news_within_60min": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": [
        "side", "entry", "stop_loss", "take_profit", "confidence",
        "higher_tf_bias", "lower_tf_bias", "trade_timeframe", "key_levels",
        "conditions_met", "high_impact_news_within_60min", "reason",
    ],
    "additionalProperties": False,
}

MONITOR_SCHEMA = {
    "type": "object",
    "properties": {
        "analyze": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["analyze", "reason"],
    "additionalProperties": False,
}

QUERY_HISTORY_TOOL = {
    "name": "query_history",
    "description": (
        "Bazadagi tarixiy shamlarni oladi. Uzoq davr uchun katta vaqt oralig'ini tanla "
        "(masalan, 10 yil uchun MN1 yoki W1). Qaytaradi: indikator xulosasi va ko'pi bilan 300 ta sham."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "timeframe": {"type": "string", "enum": list(BY_CODE)},
            "start": {"type": "string", "description": "ISO sana, masalan 2020-03-01"},
            "end": {"type": "string", "description": "ISO sana, masalan 2020-04-30"},
        },
        "required": ["timeframe", "start", "end"],
        "additionalProperties": False,
    },
}

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 4}

MAX_TOOL_ROUNDS = 3

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def cost_usd(model: str, usage) -> float:
    pin, pout = PRICES.get(model, PRICES["claude-opus-5-5"])
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (
        usage.input_tokens * pin
        + cache_write * pin * 1.25
        + cache_read * pin * 0.1
        + usage.output_tokens * pout
    ) / 1_000_000


def spent_today(session: Session) -> float:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total = session.scalar(select(func.sum(Analysis.cost_usd)).where(Analysis.ts >= start))
    return float(total or 0)


def cost_breakdown(session: Session) -> list[dict]:
    """Bugungi xarajat: tahlil turi va strategiya bo'yicha."""
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = session.execute(
        select(Analysis.kind, Analysis.strategy, func.count(), func.sum(Analysis.cost_usd))
        .where(Analysis.ts >= start)
        .group_by(Analysis.kind, Analysis.strategy)
    ).all()
    return [
        {"kind": k, "strategy": st, "calls": n, "cost_usd": round(float(c or 0), 3), "avg_usd": round(float(c or 0) / n, 3)}
        for k, st, n, c in rows
    ]


def _final_json(response) -> dict:
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude so'rovni rad etdi (refusal)")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(f"Javobda matn yo'q, stop_reason={response.stop_reason}")
    return json.loads(text)


def _run_query_history(session: Session, symbol: str, args: dict) -> str:
    tf = args["timeframe"]
    start = datetime.fromisoformat(args["start"]).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args["end"]).replace(tzinfo=timezone.utc)
    df = load_candles(session, symbol, tf, start=start, end=end)
    if df.empty:
        return json.dumps({"error": "Bu davr uchun ma'lumot yo'q"})
    step = max(1, len(df) // 300)
    sample = df.iloc[::step].tail(300)
    return json.dumps(
        {
            "timeframe": tf,
            "bars_in_range": len(df),
            "summary": summarize(df),
            "candles_ohlc": [
                [ts.strftime("%Y-%m-%d %H:%M"), round(r.open, 2), round(r.high, 2), round(r.low, 2), round(r.close, 2)]
                for ts, r in sample.iterrows()
            ],
        }
    )


def monitor(session: Session, view: dict, last_deep: dict | None) -> tuple[dict, Analysis]:
    model = settings.monitor_model
    prompt = (
        "Oltin bozorining joriy holati va oxirgi chuqur tahlil quyida. Chuqur tahlil (qimmat) hozir kerakmi? "
        "Kerak: narx muhim darajaga yetgan, trend o'zgargan, kuchli harakat bo'lgan yoki oxirgi tahlildan "
        "keyin vaziyat sezilarli o'zgargan bo'lsa. Aks holda analyze=false.\n\n"
        f"Joriy holat:\n{json.dumps(view)}\n\nOxirgi chuqur tahlil:\n{json.dumps(last_deep)}"
    )
    response = client().messages.create(
        model=model,
        max_tokens=2000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": MONITOR_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    result = _final_json(response)
    row = Analysis(
        symbol=view["symbol"], kind="monitor", model=model, input_snapshot=view, output=result,
        input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens,
        cost_usd=cost_usd(model, response.usage),
    )
    session.add(row)
    session.commit()
    return result, row


def analyze(session: Session, snapshot: dict, strategy: Strategy) -> tuple[dict, Analysis]:
    model = settings.analyst_model
    system = [
        {"type": "text", "text": BASE_SYSTEM},
        # Strategiya qoidalari o'zgarmaydi: keshlanadi
        {"type": "text", "text": f"Strategiya: {strategy.title}\n{strategy.rules}", "cache_control": {"type": "ephemeral"}},
    ]
    tools: list[dict] = [QUERY_HISTORY_TOOL]
    if strategy.web_search:
        tools.append(WEB_SEARCH_TOOL)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages: list[dict] = [
        {"role": "user", "content": f"Hozirgi vaqt: {now}\nBozor holati:\n{json.dumps(snapshot)}"}
    ]
    in_tok = out_tok = 0
    total_cost = 0.0
    response = None
    for _ in range(MAX_TOOL_ROUNDS + 1):
        response = client().beta.messages.create(
            model=model,
            max_tokens=16000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={
                "effort": settings.analyst_effort,
                "format": {"type": "json_schema", "schema": SIGNAL_SCHEMA},
            },
            system=system,
            tools=tools,
            messages=messages,
        )
        in_tok += response.usage.input_tokens
        out_tok += response.usage.output_tokens
        total_cost += cost_usd(response.model or model, response.usage)

        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        if response.stop_reason != "tool_use":
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                out = _run_query_history(session, snapshot["symbol"], block.input)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            except Exception as exc:
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": str(exc), "is_error": True}
                )
        messages.append({"role": "user", "content": results})

    result = _final_json(response)
    row = Analysis(
        symbol=snapshot["symbol"], kind="deep", strategy=strategy.key, model=response.model or model,
        input_snapshot=snapshot, output=result, input_tokens=in_tok, output_tokens=out_tok,
        cost_usd=total_cost,
    )
    session.add(row)
    session.commit()
    return result, row
