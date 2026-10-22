# Milestone 7 — مدیریت پرتفوی پژوهشی و مطالعه آینده‌نگر

وضعیت: پیاده‌سازی و اجرای محدود مهندسی انجام شد؛ مطالعه ۴۸ساعته **تکمیل نشده** است.
نتیجه اقتصادی: `INSUFFICIENT_PROSPECTIVE_EVIDENCE` و `NO_VERIFIED_ECONOMIC_EDGE`.

شاخه: `integration/atlas-milestone-7-portfolio-research`؛ مبنا `4fa99cc`.
Commit سورس منجمد: `06e4b699c44aeaa682f630a59614ffb659249c94`.
شناسه نشست جدید: `formal_48h_v1`؛ قرارداد:
`19d2936bdeda6414cda3dc2ed08582d249c087102963e2e4f16649c11fd9d457`.
Commit مستندات/تست تکمیلی پس از این Commit در تاریخچه همین شاخه قرار دارد؛ تغییر گزارش و تست، Hash سورس معاملاتی نشست را تغییر نمی‌دهد.

## ۱. منابع، ممیزی و قراردادهای حفظ‌شده

کد بیرونی کپی یا اجرا نشد. پیش از ساخت لایه جدید، قابلیت‌های موجود Atlas و منابع ثبت‌شده بررسی شدند.

| منبع | Commit و مجوز | استفاده واقعی |
|---|---|---|
| FinRL-X / FinRL-Trading | `4409abe925c904e570be78ebfb5e77ac3491dff8`؛ Apache-2.0 | ایده جدایی وزن هدف و مانده نقد از اجرا؛ مطالعه `portfolio_builder.py`، پیاده‌سازی مستقل |
| Hummingbot | `9af100d6822da7d2d0291a906c730ef172284ee2`؛ Apache-2.0 | مطالعه قرارداد اثر Fee در `trade_fee.py`؛ هیچ Connector وارد نشد |
| NautilusTrader | `a51ae015c150ef68f62d9295e3efa9534f492a4a`؛ LGPL-3.0 | فقط ایده Replay بدون انتشار دستور |
| Freqtrade | `c051e9065c5b677f03817dd1f83cb980af1ed684`؛ GPL-3.0 | فقط ایده بررسی نشت آینده؛ بدون کپی کد یا حذف Protection |
| FinMem | `be814aa47970de9bf2fdd6a1d5a60ae5cf361b46`؛ MIT | بازاستفاده از ResearchMemory موجود Atlas، نه واردکردن فریم‌ورک |

Hash فایل‌های LICENSE مجدداً در `reports/m7_reference_integration.json` کنترل شده است.
SOURCES شامل مسیرهای کشف‌شده و تفکیک ایده/کد است. هیچ سودی از README منابع به پروژه نسبت داده نشده است.

| موضوع ممیزی | نتیجه |
|---|---|
| سرمایه و موقعیت | `PaperAccount`: جدول‌های `kv`، `positions` و `events` در `shadow.sqlite` مستقل نشست؛ آغاز فرضی ۵ میلیون TMN |
| پیشنهاد معامله | LangGraph موجود، Forecast همان Champion و Reviewerهای ساختاری؛ پیشنهاد تخصیص جدید فقط پژوهشی |
| دروازه سفارش | Agent و Watch موجود هر دو از ShadowBroker و همان RiskGate عبور می‌کنند |
| اتمیک‌بودن | PaperAccount معامله را در `BEGIN IMMEDIATE` بررسی/ثبت می‌کند؛ پیشنهاد تخصیص نیز از همان DB سرمایه را اتمیک می‌خواند |
| Mark-to-Market | نقد + Bid واقعی دارایی نگهداری‌شده با فرض Fee خروج؛ فقدان Bid معتبر، مجوز حدس قیمت نیست |
| خروج نهایی | همان liquidation و RiskGate قبلی، فقط پس از Deadline واقعی نشست؛ موقعیت تسویه‌نشده حذف نمی‌شود |
| جلوگیری از تکرار | client ID و Fingerprint Broker موجود، کلید یکتای Forecast، کلید Proposal، Lease پردازش و Reconcile پایدار |
| شواهد پژوهشی | مدل‌های M5، تخصیص و مقایسه‌ها اختیار Broker، تغییر RiskGate یا Promotion ندارند |

RiskGate، Agent، ShadowBroker، PaperAccount، دو Transformer، Feature Recipe و مجوز LIVE نسبت به M6 تغییر نکرده‌اند. بررسی Diff در گزارش Integrity ثبت شده است. کلید یا `pass.txt` خوانده نشد؛ درخواست خصوصی، POST/DELETE سفارش و برداشت وجود نداشت.

## ۲. تغییرات واقعی و اجرای قابل بازتولید

فایل‌های جدید:

- `wallex_bot/atlas_portfolio.py`: پیشنهاد وزن و Delta، نقد مانده، ممیزی هزینه، کنترل Exposure/Turnover/Drawdown/هم‌بستگی/تازگی/عمق و پیش‌نمایش همان RiskGate؛ هیچ فراخوانی Broker ندارد.
- `wallex_bot/atlas_study.py`: قرارداد منجمد، گردآورنده Quote جدا از Inference، صف موعد SQLite، Lease، Stop/Resume، ثبت زمان‌های درخواست/دریافت/مشاهده/ذخیره/Scoring و شواهد حافظه.
- `wallex_bot/atlas_portfolio_report.py`: بازپخش عمق واقعی، Cohort زمانی مشترک، مقایسه مدل و تولید گزارش‌ها.
- `tests/test_milestone7_portfolio_real_only.py`: ۲۸ مورد تست جدید با آرشیو واقعی یا متادیتای غیرمالی.
- `CHANGELOG_MILESTONE7_FA.md` و بخش M7 در `third_party/SOURCES.md`.

بازاستفاده کدی اصلی: `measure_book` و توابع Sweep موجود، `ModelObservationLedger`، `DataSyncManager`، `ResearchMemory`، `DecisionLedger.replay` و مسیر کامل Agent/RiskGate/ShadowBroker قبلی. منطق اتصال و قرارداد جدید مستقل نوشته شد، چون هیچ منبعی قرارداد PIT، SQLite و Champion اختصاصی Atlas را به‌صورت آماده ندارد.

روش‌های Cash، Equal Weight، Inverse Volatility و Confidence-aware پیاده شده‌اند، اما سه روش غیرنقدی صرفاً پیشنهاد پژوهشی و مشروط به تمام شواهد لازم هستند. Inverse Volatility حداقل ۹۶ بازده واقعی هم‌تراز لازم دارد. هم‌بستگی نامعلوم، صفر فرض نمی‌شود. سه روش Volatility Targeting، Risk Parity و Minimum Variance به‌علت فقدان اعتبارسنجی مستقل، صریحاً غیرفعال‌اند.

حدود اضافه پژوهشی: وزن هر دارایی حداکثر ۱۰٪، نقد حداقل ۸۰٪، Turnover هر پیشنهاد حداکثر ۱۰٪، هزینه حداکثر ۰٫۱٪ NAV، Quote حداکثر ۳۰ ثانیه و سقف خوشه هم‌بسته ۱۰٪. حدود موجود RiskGate به‌هیچ‌وجه کاهش نیافته‌اند: سقف سفارش ۵۰۰هزار، مواجهه باز ۱میلیون، حداقل کاغذی ۱۰۰هزار TMN و Drawdown سه درصد. خروج نقدی پیشنهادی به معنی فروش انجام‌شده نیست.

Quote هر ۶۰ ثانیه یا زودتر در موعد واقعی Forecast دریافت می‌شود؛ Inference مستقل حدود هر ۹۰۰ ثانیه است. پذیرش Quote آینده فقط `[due, due+300s]` است. Timeout/Retry محدود، فاصله درخواست‌ها، Lease، صف و شروع/Deadline در SQLite پایدارند. پنجره ازدست‌رفته `UNSCORED_NO_REAL_FUTURE_QUOTE` می‌ماند؛ interpolation یا عقب‌بردن زمان انجام نمی‌شود.

در ریشه پروژه، با محیط `shbk`:

```powershell
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_study prepare
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_study run
```

دستور دوم Foreground است؛ برای توقف `Ctrl+C`، و برای Resume همان دستور را دوباره اجرا کنید. در این تحویل هیچ پردازش چندروزه یا سرویس پس‌زمینه‌ای روشن باقی نمانده است. توقف، ساعت مطالعه را به عقب برنمی‌گرداند؛ فاصله آفلاین Gap واقعی است.

کنترل و گزارش میان‌دوره‌ای:

```powershell
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_study status
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_study reconcile
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_portfolio_report --junit reports/m7_pytest.xml
```

پس از تغییر سورس/مدل، نشست قبلی قابل تجمیع با نسخه جدید نیست. برای مطالعه تازه و پیوسته، مسیر جدید بدهید؛ نشست قبلی را پاک یا بازنویسی نکنید:

```powershell
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_study prepare --session-dir atlas_store/research_challengers/milestone7/formal_48h_v2
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_study run --session-dir atlas_store/research_challengers/milestone7/formal_48h_v2
```

## ۳. نتیجه اجرای واقعی و تست‌ها

اجرای اول: `run --max-inference-cycles 1 --max-runtime-seconds 120`؛ اجرای دوم Resume واقعی: `run --max-runtime-seconds 75`.

- شروع واقعی: `2026-10-22T19:42:31Z`؛ Deadline برنامه‌ریزی‌شده: `2026-10-24T19:42:31Z`، نه پایان مشاهده‌شده.
- یک چرخه Inference: دو بازار BTC/TMN و PEPE/TMN، پنج مدل ثابت و ۱۰ Forecast؛ همگی Pending، صفر بالغ و صفر Scored.
- Resume بدون تکرار Inference: `cycles_this_process=0`؛ شمار Forecast همان ۱۰ و زمان شروع/Deadline همان مقادیر ذخیره‌شده ماند.
- چهار Quote واقعی در Ledger رسمی، از دو نوبت مشترک؛ بازه اولین تا آخرین Quote حدود ۶۱٫۵۸ ثانیه، یعنی `0.017105` ساعت. این عدد، ۴۸ ساعت یا Uptime پیوسته نیست.
- چهار درخواست موفق Sampler، صفر خطای شبکه ثبت‌شده آن؛ دو درخواست عمق دیگر توسط دو اجرای Agent موجود ثبت شدند و جزو آن چهار نمونه رسمی نیستند. DataSync دو Chunk واقعی 1m را دریافت کرد: Complete=2، Cached=0، Failed=0، Retry=0؛ رزولوشن مشتق فقط با Bucket کامل ساخته شد. مجموع این درخواست‌های عمومی مشاهده‌شده ۸ است؛ این شمارش ادعای مانیتور سراسری ترافیک دستگاه نیست.
- پنجره‌ای از Forecastهای جدید هنوز Due نشده؛ Timely Coverage برابر `null` است، نه ۱۰۰٪. Latency درخواست/دریافت هر چهار Quote در گزارش ذخیره است.
- ممیزی فقط‌خواندنی M6: هر ۳۰ Forecast توسعه‌ای اکنون فاقد Quote آینده در پنجره مجاز است؛ وضعیت مؤثر `UNSCORED_NO_REAL_FUTURE_QUOTE`، بدون تغییر Ledger قدیمی و بدون ترمیم با Quote دیرهنگام.
- ۳۵ پیشنهاد: پنج مدل × هفت روش؛ همگی Cash-only. ۷۰ پیش‌نمایش دارایی در ترکیب مدل/روش به‌علت عدم پوشش هزینه با q10 رد شد؛ این‌ها فرصت‌های مستقل نیستند. دو تصمیم واقعی Agent با `NO_TRUSTED_FORECAST` و علت Gate برابر `FINITE_Q10_FORECAST_REQUIRED` ثبت شدند.
- دو Replay واقعی: Receipt، Review و RiskGate کاملاً یکسان؛ صفر معامله کاغذی و صفر Fill واقعی؛ حساب و زنجیره Hash معتبر، نقد و NAV نقدی ۵میلیون TMN، تغییر نقد صفر.
- حافظه مستقل نشست شامل Forecast، Proposal، تصمیم/Veto و شواهد NAV کاغذی است؛ Outcome بالغ به‌صورت افزایشی و فقط پس از مشاهده واقعی ثبت می‌شود. ایجاد واقعی رویداد، علاوه بر observed/available، در بازیابی PIT کنترل می‌شود.

تست کامل:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
conda run --no-capture-output -n shbk python -m pytest -q --junitxml=reports/m7_pytest.xml
```

نتیجه نهایی: **232 passed, 5 skipped**؛ ۲۸ تست بیشتر از Baseline 204/5، بدون تغییر تست‌های قبلی.
اجرای کامل اولیه 231/5 بود؛ یک تست جدید قطع انتقال بعداً اضافه شد. در یک اجرای میانی، تست قبلی حافظه M6 به‌علت مرز زمانی بازیابی صفر رویداد دید؛ اجرای مستقل آن و اجرای کامل نهایی موفق شدند. این ناپایداری زمانی مشاهده‌شده پنهان نشده و کد حافظه برای عبور تست دستکاری نشد.

تست‌های M7 شامل حفظ Quote واقعی هنگام `ConnectionError` انتقال، Receipt نامعتبر، داده Stale، بودجه و هزینه، عدم صلاحیت روش پیچیده، Pinning سورس و Restart است. آزمون Scoring از Forecast و Quote آینده اصلیِ واقعی آرشیو قدیمی استفاده می‌کند؛ این Fixture صرفاً Legacy Replay است و هیچ نمونه‌ای به مطالعه آینده‌نگر اضافه نمی‌کند.

## ۴. هزینه، نتایج محدود و آنچه اثبات نشده

Fee برابر ۰٫۱٪ هر طرف، **فرض پژوهشی تأییدنشده** است؛ Maker/Taker حساب، Tick، Lot و حداقل واقعی Spot نامعلوم‌اند. تعداد اعشار عمومی Tick/Step تلقی نشده و حداقل OTC به Spot تعمیم نیافته است. Sweep فقط از عمق واقعی است؛ نبود عمق کافی به Gap/رد می‌انجامد، نه Fill جزئی ساختگی. هیچ Fill از Close ساخته نشده است.

دو Cohort زمانی واقعیِ مشترک امکان یک Replay توصیفی بسیار کوتاه را داد. Benchmarkها برای کنترل بودجه با وزن ۱۰٪ هر دارایی و نقد مانده تعریف شده‌اند، نه Buy-and-Hold صددرصد سرمایه:

- Cash: تغییر نقد صفر، بدون مزیت معاملاتی اثبات‌شده.
- Equal Weight دو دارایی: برآورد خالص خروج حدود `-2165.45 TMN`.
- Buy-and-Hold ده‌درصدی BTC: حدود `-999.00 TMN`؛ PEPE: حدود `-1166.45 TMN`.

این اعداد فرضِ خرید از Ask و خروج از Bid/عمق مشاهده‌شده و Fee فرضی‌اند؛ **Realized Trading PnL نیستند** و نباید برای انتخاب مدل یا ادعای برتری نقد استفاده شوند. Turnover ورود و هزینه‌های ورود/خروج در گزارش موجودند. مدل‌های M5 فقط Forecast/Proposal دارند؛ بازده تخصیص اجرا‌نشده برایشان ساخته نشده است.

هیچ مدل «بهتر» اعلام نشده: پنج مدل، هر یک دو Forecast و صفر جفت بالغ دارند. Pinball، MAE، Coverage، Calibration و CI فعلاً فاقد نمونه کافی‌اند. Latency گزارش‌شده زمان Batch پنج‌مدلیِ هر دارایی است، نه زمان اختصاصی هر مدل. حداقل از پیش تعیین‌شده برای CI بلوکی: ۴۸ ساعت و ۳۰ بلوک زمانی ۴۵دقیقه‌ای؛ Bootstrap بلوکی متوالی چهاربلوک و چهار مقایسه از پیش تعیین‌شده با Champion، بدون انتخاب/Promotion یا ادعای معناداریِ تعدیل‌شده. دارایی‌ها و افق‌های هم‌پوشان مستقل شمرده نمی‌شوند.

Drawdown، Sharpe، Win/Loss و Profit Factor معتبر گزارش نشده‌اند؛ دو Mark و صفر معامله کافی نیستند. برچسب آموزش CLOSE-to-CLOSE و ارزیابی Quote MID proxy یکسان نیستند؛ این محدودیت در هر Forecast حفظ شده است. مهندسی این مرحله سودآوری، قابلیت اجرای واقعی، مطالعه کامل، یا بهبود خارج از نمونه را اثبات نمی‌کند.

## ۵. اثر بر سامانه، خروجی‌ها و شکاف‌های Milestone 8

بهبود قابل اتکا مربوط به جمع‌آوری قابل Resume در موعد، بازتولیدپذیری، تفکیک اختیار پژوهش/اجرا، ممیزی سرمایه/هزینه و Evidence است؛ هیچ امتیاز رسمی یا بهبود PnL تأییدشده ادعا نمی‌شود.

تمام خروجی‌های خواسته‌شده در `reports/m7_*.json` و دو CSV تولید شدند؛ JUnit نیز در `reports/m7_pytest.xml` است. فایل‌های قدیمی M5/M6، مدل‌ها، حافظه و Checkpoint حذف یا بازنویسی نشده‌اند؛ داده/شواهد جدید فقط افزوده شده‌اند.

بازمانده‌ها: اجرای واقعی ۴۸–۷۲ساعته و سنجش Gap/Latency در کل دوره، رفع ناپایداری ساعت تست قدیمی، Fee و قواعد واقعی صرافی، اعتبارسنجی مستقل تخصیص پیچیده، بررسی هم‌ترازی Target و Quote proxy، و ارزیابی هزینه و ریسک اجرا در نمونه کافی. Allocation همچنان فقط پیشنهاد است؛ اتصال آن به مسیر Broker بدون مطالعه مستقل و مجوز جدید انجام نشده است.

## ۶. اطلاعات یا اقدام لازم

برای ادامه پژوهش عمومی، کلید لازم نیست. لازم است Collector در محیطی که واقعاً ۴۸/۷۲ ساعت Foreground فعال می‌ماند اجرا شود؛ یا برای شروع پیوسته تازه، مسیر نشست جدید به کار رود. خاموش‌بودن فرآیند Gap واقعی ایجاد می‌کند و با Resume جبران مصنوعی نمی‌شود.

برای تأیید Fee در آینده فقط مسیر مجاز read-only و `WALLEX_API_KEY` محیطی قابل استفاده است؛ در این مرحله چنین اطلاعاتی دریافت یا خوانده نشد. هیچ مجوز LIVE درخواست یا فعال نشده است.
