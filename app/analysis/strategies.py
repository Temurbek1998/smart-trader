"""Strategiyalar. Har biri Claude'ga alohida qoidalar bilan beriladi va natijasi alohida hisoblanadi."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Strategy:
    key: str
    title: str
    rules: str
    web_search: bool = False


STRATEGIES = [
    Strategy(
        "trend",
        "Trend bo'yicha",
        "Faqat katta vaqt oraliqlari (D1, H4) trendi yo'nalishida savdo qil. "
        "Kirish nuqtasi: H1 yoki M15 da EMA 20/50 ga qaytish (pullback) va trend yo'nalishida qayta tiklanish. "
        "Stop-loss oxirgi swing nuqtasi orqasida yoki 1.5 x ATR(H1).",
    ),
    Strategy(
        "breakout",
        "Daraja yorib o'tishi",
        "Muhim darajalarni top: oldingi kun, hafta va oy high/low, ko'p marta sinalgan narx zonalari. "
        "Signal faqat narx darajani yopilish bilan yorib o'tganda va keyingi sham tasdiqlaganda. "
        "Yolg'on yorib o'tishdan ehtiyot bo'l: London yoki Nyu-York sessiyasi ochilishidagi harakatga ko'proq ishon.",
    ),
    Strategy(
        "mean_reversion",
        "O'rtachaga qaytish",
        "Faqat D1 va H4 trendi FLAT bo'lganda ishlat. RSI(14) 30 dan past yoki 70 dan yuqori va narx Bollinger "
        "chegarasidan tashqarida bo'lsa, o'rtachaga (EMA 20) qaytishga savdo qil. Kuchli trendda bu strategiya HOLD beradi.",
    ),
    Strategy(
        "macro",
        "Fundamental va yangiliklar",
        "Oltinga ta'sir qiluvchi omillarni web qidiruv bilan tekshir: AQSh dollar indeksi (DXY), AQSh 10 yillik "
        "obligatsiya daromadi, Fed bayonotlari, bugungi va ertangi muhim iqtisodiy kalendar (CPI, NFP, FOMC), "
        "geosiyosiy xavf. Fundamental yo'nalishni texnik tahlil bilan birlashtir. Muhim yangilik oldidan 30 daqiqa "
        "ichida yangi savdo tavsiya qilma.",
        web_search=True,
    ),
]

BY_KEY = {s.key: s for s in STRATEGIES}
