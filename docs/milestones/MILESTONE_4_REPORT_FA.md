# Milestone 4 — اخبار واقعی، Sentiment و یکپارچه‌سازی PIT مشاوره‌ای

مبنا: شاخهٔ Milestone 3، commit `368a262`؛ شاخهٔ این مرحله `integration/atlas-milestone-4-news-pit`.

## ۱. نتیجهٔ واقعی و تفاوت قبل/بعد

در ممیزی شروع، `news.sqlite.articles` شامل **۹۷ عنوان واقعی و صفر sentiment** بود. پس از اجرای عمومی GDELT و سه RSS ثبت‌شده، archive نسخه‌دار جدید **۱۰۲ مقالهٔ یکتا، ۱۷۱ receipt و ۱۰۲ رکورد understanding** دارد. پنج مقاله واقعاً تازه بود و در اجرای شبکهٔ مجاز ۶۹ عنوان تکراری تشخیص داده شد. جدول و payloadهای legacy حذف یا بازنویسی نشده‌اند؛ ۹۷ ردیف اصلی و ستون sentiment قبلی دست‌نخورده‌اند.

FinBERT با GPU واقعی روی **۹۶ عنوان انگلیسی** اجرا شد و احتمال positive/negative/neutral، confidence، signed score، زمان پردازش و hash وزن/tokenizer ذخیره شد. یک عنوان فرانسوی، یک اندونزیایی و چهار عنوان با زبان نامطمئن به مدل انگلیسی فرستاده نشدند. اجرای مجدد **۹۶ cache hit، صفر inference جدید** داشت. اجرای دوبارهٔ migration و understanding نیز صفر رکورد جدید ایجاد کرد.

چهارده تعریف ویژگی خبری ساخته شد. در snapshot فعلی برای BTC/TMN، ETH/TMN، USDT/TMN و PEPE/TMN، ۱۴ خروجی عددی (با missing mask) وجود دارد، اما این به معنی آمادگی پژوهش نیست: به‌دلیل نبود polling مستند ۲۴ساعته، mask برابر ۱ و NEWS_ENHANCED آماده نیست. اخبار عمومی بازار در ارزیابی هر دارایی از خبر اختصاصی همان دارایی تفکیک شده‌اند.

## ۲. علت نبود Sentiment قبلی؛ شواهد و عدم قطعیت

`torch 2.11.0+cu128`، `transformers 5.17.0` و `langdetect` در محیط معتبر نصب‌اند و CUDA در دسترس است. cache اولیهٔ مدل FinBERT وجود نداشت؛ آزمون local-only وضعیت `SENTIMENT_MODEL_UNAVAILABLE` با `LocalEntryNotFoundError` ثبت کرد. مسیر قبلی فقط فرمان مستقل finbert داشت و در Watch به‌صورت خودکار اجرا نمی‌شد. همچنین خطا یا receipt پردازش را پایدار ثبت نمی‌کرد؛ بنابراین **علت دقیق تاریخی صفر بودن sentiment قابل اثبات نیست** و به وابستگی نصب‌نشده یا خطای حدسی نسبت داده نشده است.

اکنون پس از اولین دانلود صریح، ingestion می‌تواند حداکثر ۳۲ عنوان pending را با مدل ثابت محلی پردازش کند؛ در startup دانلود وزن انجام نمی‌شود. نبود مدل یا خطا score ساختگی تولید نمی‌کند.

## ۳. اصلاح قراردادهای Milestone 3

- منبع دو feature دفتر سفارش `provenance_verified_order_book_snapshot` است. تابع محاسبه بدون receipt hash و زمان مشاهده، خروجی Missing می‌دهد؛ OHLCV نمی‌تواند ورودی این مسیر شود. `microstructure_at` snapshot واقعی `forward_observations.sqlite` را در cutoff می‌خواند، hash کامل receipt را بررسی و spread/imbalance را از raw book دوباره محاسبه می‌کند؛ snapshot stale مقدار فعال تولید نمی‌کند. این مسیر روی receipt واقعی آزمایش شد.
- تعاریف registry به‌صورت `TIMEFRAME_TEMPLATE` هستند و نمونهٔ صریح هر timeframe در registry صادر می‌شود. نسخهٔ قرارداد `V3_1_PROVENANCE_RESEARCH_ONLY` است؛ فرمول‌های Champion و V2 تغییر نکرده‌اند.
- timestamp بازشدن، بسته‌شدن، retrieved_at و available_at جدا شدند. join تاریخی receipt-aware فقط ورودی با زمان دسترسی تأییدشده را می‌پذیرد. metadata قدیمیِ ناقص `LEGACY_AVAILABILITY_UNCERTAIN` است؛ close-time alignment اثبات دسترسی تاریخی گزارش نمی‌شود.
- feature health بین «تابع اجرا شد»، «هیچ مقدار finite ندارد»، «مقدار آخر نامعتبر است» و «آخرین مقدار معتبر» تمایز دارد. readiness علاوه بر warmup به finite بودن ورودی و تازگی وابسته است.
- بررسی واقعی CMF20 یک‌دقیقه‌ای PEPETMN: **۳٬۷۶۹ bar؛ فقط ۲۲ مقدار finite؛ ۲٬۲۷۱ high=low و ۱٬۳۳۱ حجم صفر**. نرخ نامعتبر `0.9941629079` است. CLV روی range صفر تعریف نشده و یک NaN پنجرهٔ rolling بیست‌تایی را نامعتبر می‌کند. این علت از داده استخراج شد و هیچ مقدار گمشده‌ای پر نشد.
- پروفایل‌های `CORE`, `ADVANCED`, `NEWS_ENHANCED` جدا هستند. ویژگی اختیاری خبر/advanced شرط اضافی CORE نیست. کنترل ریسک سراسری و تصمیم عملیاتی قبلی حفظ شده‌اند.

## ۴. NewsStore و قرارداد PIT

جداول جدید فقط افزایشی‌اند: documents، raw payloads، source receipts، understanding، sentiment، source/model runs و memory references. نمای `news_article_status` قرارداد یکپارچهٔ article ID، زمان‌ها، hash، زبان، processing status و model version را ارائه می‌کند.

فرمول availability متن: `max(published_at, first_observed_at)` با timestamp آگاه از منطقهٔ زمانی. تاریخ نامعتبر quarantine می‌شود. GDELT seendate با عنوان زمان مشاهدهٔ provider ثبت می‌شود و به‌عنوان تاریخ انتشار ناشر جا زده نمی‌شود.

خروجی linking یا مدل علاوه بر availability متن، باید `processed_at <= decision_cutoff` داشته باشد. در نتیجه امتیازی که امروز تولید شده به تصمیم قدیمی—even پس از اولین دریافت متن—تزریق نمی‌شود. checksum متن و raw payload در retrieval بررسی می‌شود و تغییر publisher در URL ثابت به نسخهٔ جدید تبدیل می‌شود. content hash و URL canonical برای dedup دقیق استفاده می‌شوند؛ شباهت معنایی یا استقلال تحریریه ادعا نشده است.

کل محتوا در این مرحله **عنوان واقعی RSS/GDELT** است؛ متن کامل مقاله دریافت نشده است. URL مقاله ورودی درخواست شبکه، ابزار، filesystem یا Broker نمی‌شود. تاریخچهٔ صفر خبر، outage منبع و تاریخچهٔ PIT ناکافی وضعیت‌های جدا دارند.

## ۵. منبع، نسخه و مجوز

- از archive و RSS adapter موجود، طبقه‌بندی مستقل و کتابخانه‌های نصب‌شدهٔ `requests`, `langdetect`, `transformers` استفاده شد؛ کد خارجی کپی نشده است.
- نقش خبری TradingAgents (`e8f5503e9b86d5c2710b0c76b1f686703968c9df`, Apache-2.0) و pipeline خبری/حافظهٔ FinMem (`be814aa47970de9bf2fdd6a1d5a60ae5cf361b46`, MIT) به‌عنوان مرجع مفهومی بررسی شدند. پیاده‌سازی جدید بر نیاز receipt/PIT داخلی نوشته شد؛ framework جایگزین نشده است.
- مدل: `ProsusAI/finbert@0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031`، فقط انگلیسی. وزن `model.safetensors` با SHA-256 `e5897858ff819aad7629b96ce521ae5477952d03634ef5dd30ed2d76357a9f00` کنترل می‌شود. hash tokenizer/config در receipt مدل هست.
- [model card رسمی](https://huggingface.co/ProsusAI/finbert/blob/0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031/README.md) مجوز وزن را **CC-BY-NC-SA-4.0** اعلام می‌کند. استفادهٔ این مرحله پژوهشی محلی است؛ مجوز مسابقه یا استفادهٔ تجاری احراز نشده است. هیچ وزن مدل در Git قرار نمی‌گیرد.

## ۶. ویژگی‌های خبری و Agent

چهار پنجرهٔ ۱/۳/۶/۲۴ ساعت، هرکدام count مقالهٔ مرتبط یکتا و sentiment وزن‌دار بر confidence و decay سن دارند. شش feature دیگر: تعداد source IDها در ۲۴ ساعت، بیشترین اهمیت heuristic رویداد، سن خبر، تفاوت sentiment ۱h و ۶h، نسبت شدت ۱h به ۲۴h و missing mask. فرمول همهٔ ۱۴ feature در `news_feature_registry.json` موجود است. تعداد منبع به معنی اثبات استقلال ناشران نیست.

گره خبر LangGraph اکنون evidence ساختاریافتهٔ مستقل شامل article ID، available_at، processed_at، مدل، احتمال‌ها و دلیل ارتباط را می‌گیرد. **sentiment جدید به strong_negative_urls یا veto قدیمی کپی نمی‌شود**؛ بنابراین اجرای این مرحله رفتار عملیاتی قبلی را تغییر نمی‌دهد. LLM همچنان فقط facts ساختاریافتهٔ محدود را دریافت می‌کند.

اجرای مستقیم مسیر مشاوره‌ای روی چهار دارایی، **۳۵ مرجع خبر یکتا** به حافظهٔ FinMem-inspired اضافه کرد. متن خبر در حافظهٔ دستوری ذخیره نمی‌شود، ثبت تکراری مهار می‌شود، retrieval رتبه‌بندی‌شده ۳۵ خبر را می‌بیند و زنجیرهٔ hash حافظه معتبر است. BACKTEST اجازهٔ نوشتن حافظه ندارد.

آزمون واقعی این مرحله مسیر مستقل news evidence، مدل و حافظه را اجرا کرد؛ چرخهٔ کامل LangGraph شامل PaperAccount اجرا نشد. اتصال گره به همین APIهای آزموده‌شده در سورس ثبت شده است.

## ۷. آزمون واقعی منابع و ارزیابی مشترک

آزمون اول داخل sandbox به ConnectionError رسید؛ همان خطاها ثبت شدند. اجرای مجاز شبکه: سه RSS موفق، یک GDELT ناموفق با دو تلاش و ReadTimeout؛ در مجموع پنج تلاش GET عمومی. source health تعداد/نرخ موفقیت از زمان instrumentation را نمایش می‌دهد، نه تخمین تاریخچهٔ گذشته.

دو بازوی `PRICE_TECH_ONLY` و `PRICE_TECH_NEWS` در کد از sample ID و label یکسان استفاده می‌کنند. probe ثابت Ridge فقط در صورت وجود حداقل ۱٬۲۸۰ نمونهٔ مشترک طی ۹۶ ساعت و split زمانی purged با train/validation/test مستقل فعال می‌شود؛ scaler فقط روی train fit می‌شود. در دادهٔ فعلی تعداد نمونهٔ مشترک واجد receipt/PIT **صفر** است؛ بنابراین هر دو بازو `INSUFFICIENT_PIT_NEWS_VALIDATION` هستند و MAE/calibration ساختگی گزارش نشده است. accuracy sentiment هم بدون برچسب معتبر محاسبه نشده است.

## ۸. تست و بازتولید

```powershell
conda run -n shbk python -m wallex_bot.atlas_cli news --days 2
conda run -n shbk python -m wallex_bot.atlas_cli finbert --allow-news-model-download --news-device cuda
conda run -n shbk python -m wallex_bot.atlas_cli news-audit --output-dir reports
conda run -n shbk python -m wallex_bot.atlas_cli news-evidence --symbol BTCTMN
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
conda run -n shbk python -m pytest -q
```

نتیجهٔ نهایی مجموعه: **174 passed, 5 skipped**؛ ۱۹ تست جدید در ۱۲٫۹۸ ثانیه. بارگذاری خودکار افزونه‌های محیط اشتراکی pytest باعث توقف در startup شد؛ با غیرفعال‌کردن autoload و بدون تغییر محیط/وابستگی‌ها، همان تمام تست‌های repo اجرا شدند. این استثنای محیط اجرا باید هنگام مقایسه با baseline ذکر شود.

آزمون‌ها خبر مصنوعی ندارند: عنوان‌های واقعاً archiveشده را در store موقت کپی می‌کنند یا schema و metadata غیرمالی را می‌سنجند. موارد پوشش: dedup، checksum، زمان مشاهده و پردازش، نبود مدل، cache score واقعی، زبان/link، خطای transport، candle cutoff، حذف آینده، حفظ حافظه در BACKTEST، ورود متن مخرب به evidence، provenance دفتر سفارش و نسخه‌های timeframe.

## ۹. خروجی‌ها و محدودیت‌های باز

هر ۹ خروجی در `reports/` تولید شده‌اند: `news_source_health.json`, `news_ingestion_summary.json`, `news_sentiment_coverage.csv`, `news_asset_linking_audit.csv`, `news_pit_audit.json`, `news_feature_registry.json`, `news_model_ablation.csv`, `news_agent_evidence_audit.json`, `milestone3_contract_fixes.json`.

فایل‌های اصلی تازه: `atlas_news_pipeline.py`, `atlas_news_ingestion.py`, `atlas_news_features.py`, `atlas_news_audit.py`, `atlas_feature_provenance.py` و تست Milestone 4. registry، DataSync، feature audit، agent، context/memory و CLI افزایشی اصلاح شدند. گزارش‌های feature مربوط به قرارداد V3.1 نیز بازتولید شدند.

نسخه‌های مشاهده‌شدهٔ وابستگی‌های اختیاری در `requirements-news.txt` ثبت شدند؛ هیچ بسته‌ای در محیط اشتراکی نصب/حذف/ارتقا داده نشد. ساخت torch سازگار GPU کاربر (`2.11.0+cu128`) حفظ شده است.

تاریخچهٔ خبری مستند باید به‌صورت واقعی ادامه یابد؛ snapshot فعلی برای نتیجه‌گیری اقتصادی کافی نیست. زبان فارسی مسیر Missing صریح دارد و مدل مناسبِ معتبر هنوز افزوده نشده است. Linking rule-based پوشش محدود دارد و معادل ارزیابی entity resolution برچسب‌دار نیست. واکنش قیمت به خبر، استقلال منابع، accuracy sentiment و سود خارج از نمونه اثبات نشده‌اند.

RiskGate، کد Transformer، recipe Champion و Broker با نسخهٔ مبنا مقایسه می‌شوند؛ hash checkpoint فعال نیز با manifest کنترل می‌شود. هیچ سفارش، برداشت یا POST/DELETE معاملاتی ارسال نشده و LIVE همچنان `HARD_DISABLED` است. کلید Wallex و `pass.txt` خوانده، چاپ یا commit نشده‌اند.

## Commitها

- پیاده‌سازی اصلی و تست‌های خبری: `2a437a9ee7d9b7cec8609b27f85167f301f6ade2`.
- کنترل receipt واقعی دفتر سفارش و تست تکمیلی: `624784830e4e70a738f401a05f00d9fe6f7fc3a7`.
- گزارش‌ها و این سند در commit مستقل بعدی ثبت می‌شوند؛ hash نهایی در پاسخ تحویل اعلام می‌شود.
