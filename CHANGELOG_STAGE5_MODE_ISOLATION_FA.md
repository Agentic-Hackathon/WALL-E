# Stage 5 — قرارداد اجرایی و ایزوله‌سازی حافظه

مبنای کد: Wallex Atlas Stage4، commit مرجع کاربر `1e0654f`، شاخه `integration/atlas-validation`.

## منشأ
- پلی‌بوک پروژه، بند ۲.۴: الهام از تمایز Backtest/Paper در QuantCrypt. در گزارش مرحله اول، QuantCrypt unavailable بود؛ در این مرحله کدی از آن کلون، کپی یا مشتق نشده است. این قرارداد از صفر برای Wallex Atlas نوشته شده است؛ لایسنس خارجی ادعا نمی‌شود.
- قرارداد فعلی Memory Store، RiskGate و ShadowBroker حفظ شده است؛ کد خارجی وارد پروژه نشده است.

## تغییرات
- `wallex_bot/atlas_mode.py`: enum قطعی `BACKTEST`, `SHADOW`, `LIVE` و fail-closed mode guard. `LIVE` در کل پروژه غیرفعال است.
- `wallex_bot/atlas_context.py`: BACKTEST فقط بازخوانی SQLite موجود با `mode=ro` و `PRAGMA query_only` را مجاز می‌داند؛ اگر فایل وجود نداشته باشد، نه پوشه و نه DB نمی‌سازد؛ تمام write methods، حتی ثبت lesson، خطا می‌دهند. برای پیشگیری از نشت اطلاعات آینده، رویدادهای عملیاتی موجود نیز در نمای BACKTEST به مدل داده نمی‌شوند؛ اتصال read-only فقط برای بررسی تمامیت زنجیره هش است.
- `wallex_bot/atlas_shadow.py`, `atlas_broker.py`, `atlas_watch.py`, `atlas_agent.py`, `atlas_liquidation.py`: ورودی‌های عملیاتی از حالت SHADOW عبور می‌کنند و BACKTEST/LIVE به این مسیرها دسترسی ندارند.
- `wallex_bot/atlas_validation.py`: فقط در BACKTEST اجرا می‌شود؛ خروجی صرفاً یک گزارش پژوهشی است و مدل، سفارش، حافظه یا چک‌پوینت را تغییر نمی‌دهد.
- `wallex_bot/atlas_cli.py`: `--mode` اختیاری با کنترل صریح سازگاری هر فرمان؛ `mode-status` قرارداد و محدودیت‌ها را گزارش می‌کند. `run` چرخه ترکیبی Research+Shadow است و BACKTEST محسوب نمی‌شود.
- `tests/test_stage5_mode_isolation_real_only.py`: ۶ تست قرارداد بدون داده ساختگی بازار یا معامله.

## حدود تضمین
- این Mode Contract فقط نقاط ورودی نام‌برده را محافظت می‌کند؛ sandbox امنیتی برای اجرای arbitrary Python نیست.
- در BACKTEST فایل‌های گزارش پژوهشی می‌توانند نوشته شوند؛ «عدم نوشتن» مختص دیتابیس حافظه و دفتر عملیاتی/سفارش تولیدی است.
- داده‌های بازار/کیفیت Transformer/حجم نمونه/مدت اعتبارسنجی/کارمزد تأیید نشده‌اند؛ هیچ بهبود سود یا بازده ادعا نمی‌شود.
- هیچ سفارش واقعی از این مرحله ارسال نمی‌شود؛ تطبیق سفارش با API صرافی هنوز پیاده‌سازی نشده است.

## اجرای محلی
```bash
bash scripts/apply_stage5_mode.sh
python -m pytest -q
python -m wallex_bot.atlas_cli mode-status
python -m wallex_bot.atlas_cli validate --mode BACKTEST --resolution 15 --top 8
```

توجه: `validate` محاسبات را از روی داده‌های حقیقی موجود سیستم انجام می‌دهد؛ نتایج جدید در این محیط اجرا نشده‌اند.
