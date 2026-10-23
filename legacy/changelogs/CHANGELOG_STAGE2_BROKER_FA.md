# Wallex Atlas — مرحله ۲: Broker abstraction (مبتنی بر commit مرحله اول 95206c5)

- **Source:** `grid_trading_bot` @ `fbda3dd5558a168f11e1a9733e12e1d9d8b3e1fc` (MIT): فقط مفهوم پایداری؛ `lumibot` @ `b529372528d2a1bba7f0f5e0183f6b4be8de1d7c` (در SOURCES.md به‌صورت GPL-3.0 ثبت شده): فقط مفهوم تفکیک paper/live. هیچ کد خارجی کپی یا مشتق نشده است.
- **Files:** افزودن `wallex_bot/atlas_broker.py`، تغییر محدود `atlas_shadow.py` و `atlas_agent.py` برای مسیریابی Shadow از Broker، افزودن دستور خواندنی `broker-status` در `atlas_cli.py`، تست `tests/test_atlas_broker_stage2_real_only.py`.
- **Deterministic risk:** همه معاملات فرضی همان `PaperAccount.trade` و `RiskGate.evaluate` را به کار می‌گیرند؛ سقف‌ها و سیاست ریسک تغییر نکرده‌اند.
- **Idempotency:** شناسه سفارش به صورت اتمیک با تغییر موجودی/موقعیت فرضی در `shadow.sqlite` ذخیره می‌شود. درخواست همسان دوباره معامله ایجاد نمی‌کند؛ شناسه تکراری با ورودی متفاوت رد می‌شود.
- **Live:** `WallexLiveBroker` فقط ژورنال محلی hash-chained، شناسه یکتا، حالت سفارش، kill switch همیشه فعال و رابط reconcile فقط محلی دارد. ارسال، لغو، reconciliation از صرافی، POST/DELETE و فعال‌سازی واقعی در این نسخه **وجود ندارند**.
- **Tests:** روی snapshot مرحله اول با Skillهای V3.5: `60 passed, 5 skipped`، بدون کندل، قیمت یا خبر ساختگی.
- **Not proven:** کارمزد واقعی، فهرست بازار مجاز، ارتباط API با حساب مسابقه، partial fill واقعی، recovery بعد از timeout شبکه، سودآوری، و قابلیت اجرای سفارش واقعی.
- **Next:** مرحله ۳، قرارداد liquidation نهایی TMN با داده و وضعیت واقعی سفارش و پروتکل reconciliation خواندنی، قبل از هرگونه فعال‌سازی live.
