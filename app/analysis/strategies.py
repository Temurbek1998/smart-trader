"""Strategiyalar. Har biri Claude'ga qat'iy tekshiruv ro'yxati bilan beriladi va natijasi alohida hisoblanadi.

Umumiy tamoyil: har bir shart raqamlangan. Bitta majburiy shart bajarilmasa ham HOLD.
Raqamlar (EMA, RSI, ADX, ATR, darajalar) snapshot'da tayyor beriladi, Claude ularni o'zi hisoblamaydi.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Strategy:
    key: str
    title: str
    rules: str
    web_search: bool = False


COMMON = """
Umumiy majburiy qoidalar (barcha strategiyalar uchun):
- market.market_open = false bo'lsa: HOLD.
- Kirish narxi joriy narxdan 0.3 x ATR(H1) dan uzoq bo'lmasin (bozor narxida kirish).
- Stop-loss: 1.0 dan 2.0 x ATR(H1) gacha, mantiqiy struktura (swing, daraja) orqasida. Juda yaqin stop taqiqlanadi.
- Take-profit: keyingi muhim daraja, risk/foyda kamida 1:2.
- conditions_met maydoniga bajarilgan har bir shart raqamini va qisqa dalilini yoz (masalan "T2: H4 ADX 31").
- Majburiy shartlardan bittasi bajarilmasa ham side = HOLD va conditions_met ga nima yetishmaganini yoz.
- Ochiq demo savdo shu strategiyada bor bo'lsa (open_paper_trades), yangi signal faqat u bilan bir yo'nalishda bo'lishi mumkin.
"""

STRATEGIES = [
    Strategy(
        "trend",
        "Trend bo'yicha (pullback)",
        """Maqsad: kuchli trendda vaqtinchalik orqaga qaytishdan keyin trend yo'nalishida kirish.
Majburiy shartlar:
T1. D1 trend va H4 trend bir xil (ikkalasi UP yoki ikkalasi DOWN). D1 da narx EMA 200 ning shu tomonida.
T2. H4 ADX >= 25 (trend kuchli).
T3. H1 da narx EMA 20 yoki EMA 50 ga qaytgan (oxirgi 6 sham ichida EMA ga 0.5 x ATR(H1) yaqinlikda tegish bo'lgan).
T4. Qaytishdan keyin trend tomonga tasdiq: M15 da trend yo'nalishidagi yopilish oxirgi swing high (BUY) / swing low (SELL) dan o'tgan.
T5. H1 RSI BUY uchun 40-65, SELL uchun 35-60 oralig'ida (haddan tashqari qizimagan).
Stop-loss: qaytishning swing low (BUY) / swing high (SELL) orqasida. TP: oldingi trend ekstremumi yoki 2-3 x risk.""",
    ),
    Strategy(
        "breakout",
        "Daraja yorib o'tishi (sessiya)",
        """Maqsad: London yoki Nyu-York sessiyasida muhim daraja haqiqiy yorib o'tilganda kirish.
Majburiy shartlar:
B1. market.session LONDON, LONDON_NEWYORK_OVERLAP yoki NEWYORK (Osiyo sessiyasida HOLD).
B2. Daraja market.levels dan olinadi: asia_range_high/low, prev_day_high/low yoki prev_week_high/low.
B3. M15 da shu daraja orqasida kamida 0.25 x ATR(H1) masofada yopilish bo'lgan (faqat tikan emas).
B4. Keyingi M15 sham daraja ichiga qaytib yopilmagan (yolg'on yorib o'tish emas).
B5. Yorib o'tish yo'nalishi H4 trendiga zid emas (H4 FLAT yoki bir xil yo'nalish).
B6. Daraja va keyingi qarama-qarshi daraja orasida kamida 2 x risk joy bor.
Stop-loss: yorilgan daraja ichkarisida, darajadan 0.5-1 x ATR(H1). TP: keyingi daraja.""",
    ),
    Strategy(
        "mean_reversion",
        "O'rtachaga qaytish (range)",
        """Maqsad: aniq yon harakat (range) bozorida chegaradan o'rtaga qaytishga savdo.
Majburiy shartlar:
R1. H4 ADX < 20 va H1 ADX < 22 (trend yo'q). D1 trend FLAT yoki H4 trend FLAT.
R2. H1 narx Bollinger chegarasidan tashqarida yoki unga tegib turibdi: BUY uchun bb_lower, SELL uchun bb_upper.
R3. H1 RSI BUY uchun <= 30, SELL uchun >= 70.
R4. M15 da qaytish tasdig'i: chegaradan ichkariga yopilgan sham (rad etish shami).
R5. Chegara yaqinida market.levels dagi daraja bor (prev_day yoki asia_range high/low), 0.5 x ATR(H1) ichida.
Kuchli trendda yoki muhim yangilik kunida bu strategiya doim HOLD.
Stop-loss: ekstremum orqasida 0.5-1 x ATR(H1). TP: H1 EMA 20 yoki Bollinger o'rtasi; risk/foyda 1:2 bo'lmasa HOLD.""",
    ),
    Strategy(
        "macro",
        "Fundamental filtr va yangiliklar",
        """Maqsad: fundamental yo'nalishni aniqlash va xavfli yangilik paytini ushlash.
Web qidiruv bilan tekshir (bugungi sana bilan): AQSh dollar indeksi (DXY) yo'nalishi, AQSh 10 yillik real daromadi,
Fed bayonotlari va kutilmalar, bugungi va ertangi iqtisodiy kalendar (CPI, PCE, NFP, FOMC, ishsizlik da'volari, Fed raisi nutqi),
geosiyosiy xavf va markaziy banklar oltin xaridi.
high_impact_news_within_60min: keyingi 60 daqiqada yoki oxirgi 30 daqiqada yuqori ta'sirli yangilik bo'lsa true. Aniq bilmasang true.
Majburiy shartlar:
M1. Kamida ikkita fundamental omil bir yo'nalishni ko'rsatadi (masalan DXY tushmoqda va real daromad tushmoqda: oltin uchun UP).
M2. D1 yoki H4 texnik trend fundamental yo'nalishga zid emas.
M3. high_impact_news_within_60min = false.
M4. Kirish uchun H1 da aniq daraja yoki pullback bor (umumiy qoidalardagi stop/TP talablari bajariladi).
reason ichida qaysi manbalarni ko'rganingni va yaqin yangiliklar vaqtini (UTC) yoz.""",
        web_search=True,
    ),
]

for _s in STRATEGIES:
    object.__setattr__(_s, "rules", _s.rules + "\n" + COMMON)

BY_KEY = {s.key: s for s in STRATEGIES}
