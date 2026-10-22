# گزارش Milestone 2.1 — همگام‌سازی خودکار داده هنگام راه‌اندازی

## Problem و Root Cause

Milestone 2 دانلود و provenance قابل‌ادامه را داشت، اما startup و Watch از آن به‌صورت هدفمند استفاده نمی‌کردند. در نتیجه پیش از ورود یک بازار به مسیر مدل، نبودِ دادهٔ پیوسته و هش‌تأییدشده به‌طور مستقل بررسی نمی‌شد و یک اجرای بعدی می‌توانست پنجرهٔ متحرکِ دارای دادهٔ قبلی را دوباره درخواست کند.

## Implemented Changes

- `DataSyncManager` در `wallex_bot/atlas_data_sync.py` اضافه شد. این لایه مستقل، demand مدل فعال را فقط از metadata می‌خواند، برای warmup محدود ۱ تا ۷۲ ساعت برنامه می‌سازد، با SQLite lease از تداخل دو scheduler جلوگیری می‌کند و وضعیت run را پایدار ثبت می‌کند.
- برنامه‌ریز ابتدا Spot/TMNهای فعالِ اولویت‌دار را می‌گیرد و scopeهای `tmn`، `spot` و `catalog` را نیز برای کارهای پایین‌اولویت دارد. درخواست فقط native source (`1`، `60`، `1D`) است؛ `15` و سایر رزولوشن‌های مشتق فقط از bucket کامل و هش‌تأییدشده ساخته می‌شوند.
- برنامه‌ریز به‌جای تکرار chunk سه‌ساعته، دقیقاً runهای timestamp گمشده را صف می‌کند. یک grace برابر یک candle منبع برای انتشار API دارد؛ بنابراین سیستم در هر دقیقه دنبال ساعت نمی‌دود. gap هرگز interpolate یا fabricate نمی‌شود.
- `atlas_archive.harvest(..., windows=...)` اکنون پنجره‌های native صریح را با همان progress، limiter، retry، backoff، hash و conflict policy Milestone 2 انجام می‌دهد. explicit window دیگر discovery اضافی انجام نمی‌دهد. پاسخ واقعاً unavailable با `SOURCE_UNAVAILABLE` پایدار ثبت می‌شود.
- `atlas_agent.cycle` پیش از ساخت graph، sync محدود اجرا می‌کند و در نبود ورودی پیوستهٔ معتبر با `NO_PAPER_ACTION_DATA_NOT_READY` متوقف می‌شود. Transformer، Champion و Risk Gate تغییر نکرده‌اند.
- هر چرخهٔ `atlas_watch.run` sync محدود دارد. اگر حتی یکی از بازارهای منتخب ready نباشد، `DATA_SYNC_INPUT_NOT_READY` ثبت می‌شود و `shadow_cycle` فراخوانی نمی‌شود.
- scheduler قابل توقف `run_continuous(stop_event, ...)` افزوده شد؛ thread پنهان ایجاد نمی‌کند و lifecycle با caller است. lease SQLite قابلیت restart و اجرای همزمان امن را حفظ می‌کند.
- فرمان‌ها: `data-sync-plan` (همیشه dry-run)، `data-sync-run` و `data-sync-status`. `account-read-status` جدا است، فقط در صورت وجود `WALLEX_API_KEY` endpointهای allowlist read-only را می‌خواند و LIVE را فعال نمی‌کند. `pass.txt` نه خوانده، نه چاپ و نه ثبت شد.

## Source و License

کد این milestone مستقل نوشته شد و هیچ کدی از پروژهٔ ثالث کپی نشده است. از زیرساخت واقعی، هش، progress و policy نگهداری chunk در commit `2a1cfac` / `73fe817` استفاده شده است. بنابراین license جدید یا attribution کد خارجی ندارد.

## Modified Files

- `wallex_bot/atlas_data_sync.py`
- `wallex_bot/atlas_archive.py`
- `wallex_bot/atlas_agent.py`
- `wallex_bot/atlas_watch.py`
- `wallex_bot/atlas_cli.py`
- `wallex_bot/wallex_api.py`
- `tests/test_milestone2_1_data_sync_real_only.py`
- `reports/data_sync_before_after.json`
- `reports/data_sync_restart_test.json`
- `reports/data_sync_status.json`

## Commands

```powershell
conda run -n shbk python -m wallex_bot.atlas_cli data-sync-plan --top 8 --sync-hours 48
conda run -n shbk python -m wallex_bot.atlas_cli data-sync-run --top 8 --sync-hours 48
conda run -n shbk python -m wallex_bot.atlas_cli data-sync-status
conda run -n shbk python -m wallex_bot.atlas_cli account-read-status
conda run -n shbk python -m pytest -q
```

## Tests و دادهٔ واقعی

نتیجهٔ نهایی: `149 passed, 5 skipped` در ۵٫۹۶ ثانیه.

اجرای واقعی public-only روی `PEPETMN` انجام شد. ابتدا کمبود تشخیص داده شد و ۳ پنجرهٔ native یک‌دقیقه‌ای با **۳ درخواست واقعی** دریافت شد؛ صفر retry، صفر failure، صفر conflict و صفر overwrite داشت. پس از گذر زمان، تنها بازهٔ جدید `2026-10-22T13:33:00Z` تا `13:39:00Z` درخواست شد. اجرای فوری بعدی در همان مرز settled، **۰ درخواست شبکه** برنامه‌ریزی کرد. Process جداگانه status پایدار ledger را دید. جزئیات قابل‌ماشین در سه JSON گزارش قرار دارد.

تست controlled outage بدون ساخت candle/quote انجام شد: failure transport فقط `FAILED` progress ثبت کرد و zero chunk نوشت. تست Watch نیز ثابت می‌کند که با readiness نامعتبر، مسیر shadow decision اصلاً فراخوانی نمی‌شود.

## What This Does Not Prove

- سودآوری، برتری Champion، دقت Transformer، تعداد معامله یا کیفیت fill را اثبات نمی‌کند.
- دسترسی به کل تاریخچهٔ provider یا دوام همهٔ حالت‌های outage واقعی را اثبات نمی‌کند.
- `account-read-status` بدون `WALLEX_API_KEY` فقط گزارش unset داد؛ موجودی TMN، کارمزد و تشخیص اعتبار مسابقه در این اجرا قابل اثبات نیست.
- هیچ سفارش، POST/DELETE، برداشت یا LIVE activation انجام نشده است.

## Rubric اثر و موارد باز

این تغییر به امتیازهای reproducibility، PIT/provenance، safety، مدیریت نقص داده، retry/resume و operational readiness کمک می‌کند. معیارهای اقتصادی (سود خالص خارج از نمونه پس از هزینهٔ تأییدشده و drawdown کنترل‌شده) هنوز باز هستند و این milestone دربارهٔ آن‌ها ادعایی ندارد.

## Commit

commit اصلی Milestone 2.1: `a1883d6fb99383e28bef05f62680408e65868337` (`feat: automate bounded startup data sync`).
