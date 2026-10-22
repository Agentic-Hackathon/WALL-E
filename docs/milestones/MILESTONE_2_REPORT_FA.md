# گزارش Milestone 2 — پوشش دادهٔ بازار و کیفیت Point-in-Time

## Problem

پروژه پیش از این chunkهای واقعی و هش‌شده داشت، اما برای تمام بازارهای catalog و تمام رزولوشن‌های پشتیبانی‌شده یک ماتریس واحد نداشت که تفاوتِ «دادهٔ معتبر»، «gap واقعی»، «دادهٔ مشتق‌نشده»، «خطای ثبت‌شده» و «اصلاً پروب‌نشده» را روشن کند. Downloader نیز برای retry/progress/conflict-provenance قرارداد یکپارچه و قابل گزارش نداشت.

## Root Cause

API عمومی UDF تنها `symbol`, `resolution`, `from` و `to` را مستند می‌کند و شروع واقعی تاریخچه، cursor/page و سقف تعداد کندل را تضمین نمی‌کند. مستند عمومی رزولوشن‌های بیشتری نام می‌برد، اما پاسخ واقعی همان لحظه برای همهٔ آن‌ها همان grid درخواستی را بازنگرداند. پیش از این، اطلاعات receipt/available برای chunkهای جدید به‌صورت یک provenance صریح و جدا ثبت نمی‌شد و catalog-wide coverage از روی فایل‌های هش‌شده استخراج نمی‌شد.

## Implemented Changes

- `atlas_archive.py` اکنون progress پایدار هر پنجره، retry محدود با backoff، limiter مشترکِ شروع درخواست و workerهای کنترل‌شدهٔ فقط-GET دارد. نوشتن SQLite و فایل فقط در thread اصلی انجام می‌شود.
- چنانچه پاسخ تازه با chunk پذیرفته‌شده تفاوت داشته باشد، chunk قدیمی جایگزین نمی‌شود؛ evidence تازه در `conflicts/` و `archive_conflicts` نگهداری می‌شود.
- `chunk_observations` زمان `retrieved_at` و `available_at` محلی، source resolution و endpoint را برای chunkهای جدید نگه می‌دارد. `available_at` زمان دریافت محافظه‌کارانه است، نه timestamp تاریخی کندل.
- `atlas_data_quality.py` و فرمان `data-quality-audit` ماتریس کامل catalog، صحت hash/grid، gapها، رخدادهای دانلود، PIT و پوشش دفتر سفارش را تولید می‌کنند.
- candle مشتق فقط از bucket کامل و صحت‌سنجی‌شده ساخته می‌شود؛ فاصلهٔ زمانی هرگز با قیمت ساختگی پر نمی‌شود.
- Champion، RiskGate، LangGraph، Watch، Transformerها و LIVE تغییر رفتاری ندارند. هیچ API سفارش/حساب فراخوانی نشد.

## Modified Files

- `wallex_bot/atlas_archive.py`
- `wallex_bot/atlas_data_quality.py`
- `wallex_bot/atlas_cli.py`
- `tests/test_milestone2_data_quality_real_only.py`
- `reports/data_coverage.csv`
- `reports/data_coverage_summary.json`
- `reports/data_download_incidents.json`
- `reports/timeframe_integrity.json`
- `reports/pit_data_quality.json`
- `reports/download_progress.json`
- `docs/milestones/MILESTONE_2_REPORT_FA.md`

## Tests

```powershell
conda run -n shbk python -m pytest -q
```

نتیجه: `141 passed, 5 skipped` در ۵٫۸۱ ثانیه. دو تست جدید هیچ OHLCV، quote، fill یا خبر مصنوعی نمی‌سازند: قرارداد خروجی audit خالی و رد symbol نامعتبر پیش از شبکه را می‌سنجند.

## Real Data Used

### مستند و پاسخ عمومی

مستند رسمی Wallex برای `GET /v1/udf/history` پارامترهای `symbol`, `resolution`, `from`, `to` را نشان می‌دهد؛ endpointهای عمومی را با سقف کلی ۱۰۰ درخواست در ثانیه بیان می‌کند، اما pagination و earliest-history قابل‌اتکا برای UDF اعلام نمی‌کند. پروژه به‌طور محافظه‌کارانه با فاصلهٔ پیش‌فرض ۰٫۳۵ ثانیه بین شروع درخواست‌ها کار می‌کند؛ اجرای محدود این milestone از ۰٫۲۵ ثانیه استفاده کرد، بسیار پایین‌تر از سقف اعلام‌شده.

Probe عمومی واقعی روی `BTCTMN` در ۲۰۲۶-۱۰-۲۲ ثبت شد:

- `1`، `60` و `1D` در پاسخ همان لحظه grid درخواستی را داشتند.
- درخواست `15` پاسخ یک‌دقیقه‌ای داد؛ `240`، `480` و `720` پاسخ ساعتی دادند؛ `2D` و `3D` پاسخ روزانه دادند. هیچ‌یک native نام‌گذاری نشدند.
- `180` و `360` با `s=error` پاسخ دادند، با آن‌که در مستند نام برده شده‌اند.
- برای ۱ دقیقه، بازهٔ ۱۲ ساعت ۷۱۹ و بازهٔ ۲۴ ساعت ۱٬۴۳۹ کندل داد؛ بازهٔ ۴۸ ساعت `s=no_data` داد. این مشاهده سقف دقیق provider را اثبات نمی‌کند. نمونهٔ ۶۰ دقیقهٔ ۳۶۵ روزه ۶۹۶ و نمونهٔ روزانهٔ ۳۶۵ روزه ۳۶۵ کندل بازگرداند.

به همین علت، archive فقط `1`, `60`, `1D` را source-native می‌داند و بقیهٔ رزولوشن‌ها را صرفاً از bucketهای کامل همین منابع مشتق می‌کند.

### اجرای محدود واقعی

فرمان اجراشده:

```powershell
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_cli archive-all --scope all-spot --days 1 --resolutions 1,60,1D --limit-markets 3 --delay 0.25 --workers 2 --retries 1 --backoff-seconds 0.25
```

فقط Public Read API استفاده شد. زمان دریافت از `13:03:54.275325Z` تا `13:04:01.876473Z` بود: ۱۵ پنجرهٔ واقعی جدید، ۳۳ cache معتبر، صفر retry، صفر failure و صفر conflict. هیچ دادهٔ قبلی حذف یا overwrite نشد. `atlas_store` هم‌زمان ممکن است توسط watch موجود تغییر کند؛ بنابراین افزایش snapshot کل store از ۳٬۷۶۰ به ۳٬۸۰۷ chunk منحصراً به این فرمان نسبت داده نمی‌شود.

## Experimental Results

`reports/data_coverage.csv` همهٔ ۴۶۹ بازار کشف‌شده × ۱۳ رزولوشن را دارد: **۶٬۰۹۷ ردیف**. شمارش وضعیت‌ها:

| وضعیت | تعداد |
|---|---:|
| `ARCHIVED_VERIFIED_CONTIGUOUS` | ۳۲ |
| `ARCHIVED_VERIFIED_WITH_GAPS` | ۹۴ |
| `DERIVATION_NOT_MATERIALIZED` | ۲۹۴ |
| `PUBLIC_SOURCE_UNAVAILABLE_OR_INCOMPLETE` | ۵۰ |
| `NOT_ARCHIVED_NOT_PROBED` | ۵٬۶۲۷ |

برای coverage کل تاریخی مقدار `UNKNOWN_UNPROVEN_API_HISTORY_START` ثبت شده است. فقط coverage بین اولین و آخرین candle آرشیویِ هش‌تأییدشده محاسبه می‌شود؛ ۲۰٬۰۲۶ bar گمشده در همین پنجره‌های قابل مشاهده باقی مانده‌اند و پر نشده‌اند.

در زمان گزارش، store دارای ۴۶۹ asset، ۳٬۸۰۷ chunk، ۳۷۹٬۱۱۴ candle، ۴۸ رکورد progress و ۱۵ observation provenance جدید بود. ۳٬۷۹۲ chunk قدیمی فقط `observed_at` legacy دارند و نمی‌توان availability تاریخی آن‌ها را با قطعیت پس‌نگر اثبات کرد.

دفتر order book تاریخی مستقل از OHLCV است: `forward_observations.sqlite` شامل ۲۱۰ receipt واقعی برای ۸ نماد است. CSV برای هر بازار وضعیت جداگانهٔ توان ساخت microstructure و Ask-to-Future-Bid ثبت می‌کند؛ برای ۴۶۱ نماد دیگر receipt تاریخی کافی وجود ندارد. هیچ دفتر سفارشی از کندل ساخته نشده است.

## Limitations

- این milestone «ممیزی کامل» ایجاد می‌کند، نه ادعای دریافت کامل تاریخچه. ۵٬۶۲۷ ردیف صریحاً unprobed هستند.
- endpoint عمومی earliest available را تضمین نکرده است؛ `first_available` تاریخی عمداً `UNKNOWN_UNPROVEN_BY_PUBLIC_API` است.
- مشاهدهٔ ۴۸ ساعت ۱ دقیقه‌ای `no_data` یک محدودیت دقیق یا دائمی API را ثابت نمی‌کند.
- ۲۱۲ incident تاریخی (غالباً `MarketDataError` یا `ValueError`، همراه با timeout/connection/SSL) ثبت شده‌اند؛ این فایل‌ها diagnostics هستند، نه سفارش یا fill.
- فقط receiptهای جدید `retrieved_at/available_at` جدا دارند؛ legacy evidence برای PIT گذشته محدودیت دارد.
- snapshotهای order book کوتاه‌مدت هستند و fill واقعی یا عمق تاریخی کامل را اثبات نمی‌کنند.

## Risks

- نرخ و رفتار UDF ممکن است تغییر کند؛ adapter فقط grid واقعی را می‌پذیرد و باید گزارش را پیش از هر آزمایش تازه بازتولید کرد.
- درخواست گستردهٔ catalog باید با همان limiter و progress ادامه یابد؛ نبود رکورد نباید به‌عنوان نبود بازار یا صفر حجم تعبیر شود.
- derived data تنها پس از bucket کامل ساخته می‌شود؛ این ممکن است coverage را کاهش دهد اما leakage یا OHLCV جعلی ایجاد نمی‌کند.
- هیچ‌کدام از این داده‌ها سودآوری، هزینهٔ واقعی، قابلیت اجرا، یا مجوز LIVE را اثبات نمی‌کند.

## Commit Hash

`PENDING_MILESTONE_2_AUDIT_COMMIT` — پس از ثبت commit اصلی، hash واقعی در commit تکمیلی provenance وارد می‌شود.

## Next Actions

1. اجرای تدریجیِ public-only با progress باقی‌مانده را در بازه‌های محدود ادامه دهید؛ ابتدا marketهایی که واقعاً برای پژوهش Spot/TMN لازم‌اند.
2. قبل از هر training، فقط ردیف‌های `ARCHIVED_VERIFIED_CONTIGUOUS` با availability قابل اثبات را انتخاب کنید.
3. برای تعداد بیشتری از بازارهای مجاز، receipt دفتر سفارش واقعی و time-matched future receipt جمع‌آوری کنید؛ از OHLCV به‌عنوان جایگزین آن استفاده نشود.
