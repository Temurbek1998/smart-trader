# Smart Trader

Oltin (XAUUSD) bozorini Claude API orqali chuqur tahlil qilib, ishonchli signal beradigan va ularni demo hisobda sinaydigan tizim.

- **Ma'lumot:** MetaTrader 5 (asosiy) yoki Yahoo (faqat sinov uchun). 9 ta vaqt oralig'i: M1, M5, M15, H1, H4, D1, W1, MN1, Y1.
- **Tahlil:** `claude-haiku-5-5` har 5 daqiqada arzon kuzatadi; kerak bo'lsa `claude-opus-5-5` 4 ta strategiya bo'yicha chuqur tahlil qiladi. Opus bazadagi butun arxivdan `query_history` asbobi bilan qo'shimcha davr so'raydi, "macro" strategiyasi esa web qidiruv bilan DXY, obligatsiyalar, Fed va iqtisodiy kalendarni tekshiradi.
- **Ishonch qoidasi:** signal faqat D1/H4 va H1/M15 bir yo'nalishda, ishonch ≥ 0,7 va risk/foyda ≥ 1:1,5 bo'lsa e'lon qilinadi.
- **Demo savdo:** har signal balansning 1% xavfi bilan demo savdo ochadi; stop-loss yoki take-profit tegsa yopiladi. `EXECUTE_ON_MT5=true` bo'lsa, MT5 demo hisobida ham ochiladi.
- **Web panel:** grafik, signallar, demo savdolar, strategiyalar reytingi, kunlik Claude xarajati.

## O'rnatish

Talablar: Python 3.11+, Docker (PostgreSQL uchun). MT5 bilan ishlash uchun Windows va o'rnatilgan MetaTrader 5 terminali.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env
docker compose up -d            # PostgreSQL + TimescaleDB
```

`.env` faylida kamida `ANTHROPIC_API_KEY` ni to'ldiring. MT5 demo hisob ma'lumotlarini `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` ga yozing (yoki terminalga oldindan kiring). Serverda `WEB_PASSWORD` ni albatta qo'ying.

## Ishga tushirish

```bash
python -m app.data.collector          # birinchi marta: barcha vaqt oraliqlari tarixini yuklash
uvicorn app.web.main:app --host 0.0.0.0 --port 8000
```

Panel: http://localhost:8000. Rejalashtiruvchi web bilan birga ishlaydi (`MONITOR_EVERY_MIN` daqiqada bir sikl). "Hozir tahlil qilish" tugmasi darhol chuqur tahlil boshlaydi.

Bitta siklni qo'lda ishga tushirish: `python -m app.engine --deep`

## 10+ yillik tarix

MT5 broker serveridagi tarix odatda bir necha yil bilan cheklangan. Uzoqroq tarix uchun Dukascopy'dan XAUUSD M1 ma'lumotini CSV qilib yuklab, import qiling:

```bash
python -m app.data.import_csv xauusd_m1.csv --timeframe M1
```

M1 dan barcha katta vaqt oraliqlari (M5 ... Y1) avtomatik hisoblanadi.

## Tuzilma

| Fayl | Vazifasi |
| --- | --- |
| `app/data/providers.py` | MT5 va Yahoo narx manbalari, MT5 buyurtma yuborish |
| `app/data/collector.py`, `store.py`, `import_csv.py` | Shamlarni yuklash, saqlash, CSV import |
| `app/indicators.py` | EMA, RSI, MACD, ATR, Bollinger |
| `app/analysis/snapshot.py` | Bozor holatini Claude uchun JSON'ga yig'ish |
| `app/analysis/claude_analyst.py` | Haiku monitoring, Opus chuqur tahlil, xarajat hisobi |
| `app/analysis/strategies.py` | 4 ta strategiya qoidalari |
| `app/analysis/signals.py` | Ishonchli signal qoidasi |
| `app/trading/paper.py` | Demo savdo dvigateli |
| `app/engine.py` | Bitta to'liq ish sikli |
| `app/web/` | FastAPI web panel |

## Testlar

```bash
pytest -q
```

Testlar Claude API'ni chaqirmaydi (soxta mijoz bilan), haqiqiy pul ham ishlatilmaydi.

## Muhim

Bu tizim faqat demo savdo uchun. Claude kuchli tahlilchi, lekin bozorni oldindan bila olmaydi. Haqiqiy pulga o'tishdan oldin kamida 1-2 oy demo natijalarini kuzating.
