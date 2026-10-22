# گزارش واقعی Milestone 6 — معماری Agent و مشاهده آینده‌نگر

## نتیجه و حدود تکمیل

مسیر مشترک Agent/Watch، حافظه افزایشی PIT، مشاهده پنج مدل، reconciliation واقعی، اجرای foreground قابل Resume و ارزیابی Shadow چندروزه پیاده‌سازی شدند. **هیچ مزیت اقتصادی اثبات نشده و دوره ۴۸/۷۲ساعته سپری نشده است.**

شاخه `integration/atlas-milestone-6-agent-forward`؛ مبنا `26cd878`؛ Commit کد هنگام تولید گزارش `0977b35aaab7c86550a8ee336be76e4d825ffd86`. گزارش در Commit جدا تحویل می‌شود.

## ۱. منبع و تغییرات واقعی

هفت مرجع با Commit، مسیر واقعی و LICENSE در `m6_reference_repositories.json` و `third_party/SOURCES.md` ثبت شده‌اند. TradingAgents: Apache-2.0؛ FinMem: MIT؛ Hindsight: MIT با copyright جای‌نگهدارنده؛ FinRL-Trading/FinRL-X: Apache-2.0؛ NautilusTrader: LGPL-3.0؛ Freqtrade: GPL-3.0؛ Hummingbot: Apache-2.0. همه استفاده مفهومی‌اند، **صفر خط کد خارجی کپی و هیچ کد خارجی اجرا نشد**. منابع GPL/LGPL فقط برای مطالعه بودند. نتیجه‌های README/مقالات به Atlas نسبت داده نشدند.

به‌جای جایگزینی Framework، LangGraph با SqliteSaver، ContextStore، رتبه‌بندی FinMem-inspired، ForwardLedger، DataSync، PaperAccount و ShadowBroker موجود توسعه یافتند. RiskGate، Broker، Transformer، Feature Recipe و Champion تغییر نکردند. تابع قدیمی Shadow برای ممیزی با نام `_legacy_shadow_cycle` حفظ شد؛ مسیر عمومی Watch اکنون `run_assets -> atlas_agent.cycle` است. هفت نقش Technical، News، Forecast، Regime، Portfolio، Risk و Explanation واقعاً JSON می‌سازند، اما عامل‌های قطعی شواهدمحور هستند، نه هفت LLM. LLM اختیاری پیش‌فرض خاموش است و خروجی آن هیچ ورودی Broker را تغییر نمی‌دهد.

Per-asset readiness و Fail-closed مستقل حفظ شد. Watch بررسی فنی Agent را هم دریافت می‌کند؛ این تغییر ممکن است اقدام را کمتر کند و به معنی بهبود بازده نیست. نبود خبر Core را متوقف نمی‌کند. Portfolio پیش از هر تصمیم با Bid واقعی همه دارایی‌های نگه‌داری‌شده mark می‌شود؛ ارزیابی RiskGate دوباره در تراکنش اتمیک Broker انجام می‌شود. ID سفارش کاغذی به نماد/کندل/مدل مقید است؛ استفاده مجدد با شواهد متفاوت Fail-closed می‌شود.

## ۲. اجرای واقعی و فایل‌ها

Session واقعی: `D:\Hackaton\Wallex\wallex_agent_v3\atlas_store\research_challengers\milestone6\forward_v1`؛ archive اصلی دست‌نخورده از نظر داده پذیرفته‌شده باقی ماند و فقط دریافت محدود/مشتق‌سازی معتبر به آن افزوده شد. حساب این مطالعه در همان Session با سرمایه **فرضی** ۵ میلیون TMN جدا از حساب کاغذی قدیمی ساخته شد. 8 چرخه کامل گراف در 4 چرخه گردآورنده اجرا شد؛ توزیع تصمیم‌های واقعی Shadow: `{'NO_TRUSTED_FORECAST': 8}`. هیچ سفارش یا Fill واقعی صرافی وجود نداشت. تمام Checkpointهای قدیمی نگه‌داری شدند.

تعداد چرخه گردآورنده: **4**؛ پیش‌بینی آینده‌نگر واقعی: **30**؛ بالغ و امتیازدهی‌شده با Quote واقعی: **0**. مدت بین اولین و آخرین Quote: **0.380123 ساعت**، نه ۴۸ ساعت. اجراهای دوم/سوم پس از Restart همان Session را ادامه دادند؛ شمار پیش‌بینی ثبت‌شده به‌ترتیب `[10, 0, 10, 10]` بود؛ اجرای دوم **۱۰ Cache Hit مدل** و صفر پیش‌بینی تکراری جدید داشت. این اعداد موفقیت Uptime یا استراتژی نیستند.

Observer تعداد 8 درخواست Depth عمومی داشت؛ هر گراف Agent نیز Quote عمومی مستقل و در صورت وجود موقعیت، Bid واقعی دارایی‌های نگه‌داری‌شده را دریافت می‌کند. 12 Window کندل در DataSync گردآورنده تکمیل شد؛ دریافت‌های اضافی Sync خود Agent در ledger اصلی ثبت شده‌اند و در این شمار گردآورنده نیستند. Cache دانلود 0 و خطاهای ثبت‌شده شبکه در Collector 0 است. هیچ endpoint حساب/سفارش/برداشت یا API Key استفاده نشد. `pass.txt` خوانده نشد.

پنج مدل از پیش تعیین‌شده: Champion بدون تغییر، LightGBM Quantile M5، PatchTST منتخب Validation در M5، Zero/Persistence و توزیع کوانتایل برچسب Train. مدل‌های پژوهشی فقط مشاهده دارند و به Broker دسترسی ندارند. ثبت یک گروه مدل در Timestamp و Quote مشترک انجام می‌شود؛ یک (مدل،نماد،Cutoff) دوباره ثبت نمی‌شود. شکست مدل‌ها و خطاها در Cycleها نگه‌داری می‌شوند. هیچ افق ۱۵/۶۰/۱۸۰دقیقه‌ای از خروجی ۴۵دقیقه‌ای ساخته نشد.

هدف آموزش Close-to-Close است؛ نتیجه Quote-origin، Mid-to-Mid **Proxy** است و Ask-to-Future-Bid با کارمزد فرضی از Fill/PnL جدا می‌ماند. دو زمان `model_target_end` و `quote_due` ذخیره شده‌اند؛ این دو هدف هم‌ارز معرفی نمی‌شوند. فقط اولین Quote واقعی در [due,due+300s]، با SHA معتبر، مجاز است. نبود آن `UNSCORED_NO_REAL_FUTURE_QUOTE` می‌ماند. ساعت هرگز برای بالغ‌کردن پیش‌بینی جلو برده نمی‌شود. داده قدیمی برای ساخت پیش‌بینی جدید گذشته استفاده نشده است.

حافظه جدید در جدول افزایشی `research_memory_v6` همان ContextStore است؛ هیچ رکورد قبلی بازنویسی نشد. وضعیت فعلی لایه‌ها: `{'DECISION_RISK_VETO': 8, 'NEWS_EVENT': 20, 'PAST_FORECAST': 30, 'RECENT_MARKET_CONTEXT': 8}`؛ هر هفت نوع لایه پشتیبانی می‌شوند، اما Outcome/درس تأییدشدهٔ بدون شواهد ساخته نمی‌شود. مشاهده، دسترس‌پذیری و زمان واقعی ایجاد همگی باید <= Cutoff باشند. رتبه‌بندی importance/recency/relevance قطعی و محدود است. گراف فقط ID/Hash/وضعیت حافظه را در Context می‌بیند، نه متن خبری در جایگاه دستور. Replay هیچ حافظه‌ای ثبت نمی‌کند و زنجیره‌های قدیم و جدید معتبرند.

فایل‌ها: `atlas_agent.py`, `atlas_shadow.py`, `atlas_watch.py`, `atlas_memory.py` توسعه یافتند؛ `atlas_review.py`, `atlas_orchestration.py`, `atlas_prospective.py`, `atlas_forward_watch.py`, `atlas_m6_report.py` و تست M6 اضافه شدند. دو helper در `atlas_m5_inference.py` و `atlas_m5_report.py` نیز اصلاح شدند تا اجرای Smoke به‌صورت پیش‌فرض گزارش تاریخی M5 را بازنویسی نکند و فقط تولید صریح گزارش مقصد را بنویسد؛ مقادیر و فایل‌های گزارش M5 حفظ شدند. تمام ده JSON الزامی و JUnit واقعی در reports موجودند. در Snapshot مقایسه، مسیر قبلی Watch روی **همان شواهد واقعی جدید** به‌صورت Counterfactual دوباره evaluate شد؛ این نتیجه اجرای تاریخی مسیر قبلی یا معامله قدیمی نیست.

## ۳. تست‌ها و Replay

**204 passed, 5 skipped، 0 failed، 0 errors**؛ Baseline برابر 190 passed, 5 skipped بود. هر ۱۹۰ تست قبلی حفظ شد. ۱۴ تست جدید مسیر مشترک، نبود خبر، آمادگی مستقل بازار، RiskGate سراسری، PIT حافظه/خبر، منع اختیار LLM/Promotion، ثبت آینده‌نگر واقعی، Timestamp مشترک، lease دو نمونه، Restart، منع جلو بردن ساعت و Replay بدون اثر جانبی را پوشش می‌دهد.

یک اجرای میانی ۲۰۳ موفق، یک شکست و ۵ Skip داشت: مقایسه زیرمیلی‌ثانیه‌ای دو ساعت در تست تازه حافظه race ایجاد می‌کرد. تست با Cutoff واقعی قدیمی اصلاح شد تا دقیقاً جلوگیری از نشت بر اساس زمان ایجاد را بسنجد؛ اجرای کامل نهایی بالا عبور کرد. این شکست پنهان نشده و در JSON تست ثبت است.

تست reconciliation یک Forecast از قبل ثبت‌شدهٔ legacy و همان Quoteهای واقعی مبدأ/آینده را در Fixture جدا کپی و نتیجه قبلی را بازتولید می‌کند؛ این تست **هیچ Outcome جدید آینده‌نگر M6 نیست**. برای M6 فعلی تعداد بالغ همان 0 است. 8 تصمیم واقعی Replay شدند؛ همه Reviewها و تمام خروجی‌های RiskGate یکسان بودند. قیمت، کندل، خبر، سفارش و Fill آزمایشی جعلی تولید نشد.

## ۴. چه چیزی اثبات نمی‌شود؟

هیچ برتری Challenger نسبت به Baseline در آینده‌نگر هنوز قابل محاسبه نیست؛ نتایج M5 همان نتایج تاریخی باقی مانده‌اند. سود واقعی، هزینه تأییدشده، نقدشوندگی پایدار، بازده مستقل، کنترل Drawdown طی ۴۸ ساعت و Uptime چندروزه اثبات نشده‌اند. وضعیت استراتژی `PENDING_INSUFFICIENT_48H_PROSPECTIVE_COVERAGE` است. Cash کاغذی فعلی 5000000.0 TMN و پرتفوی بدون موقعیت است؛ این سود یا Fill نیست. نتیجه اقتصادی `NO_VERIFIED_ECONOMIC_EDGE` باقی می‌ماند.

## ۵. اثر بر سامانه و Milestone 7

این مرحله معماری، ایمنی، بازتولید، ثبت شواهد و جداسازی پژوهش را بهتر می‌کند، نه امتیاز اقتصادی ادعایی. اجرای محدود تمام شده و **سرویس دائمی فعال نگذاشته‌ایم**. lease آزاد شده، Session قابل ادامه است و به‌تنهایی Scheduler یا فایل RUNNING اثبات زنده‌بودن فرآیند نیست. برای مطالعه ۴۸/۷۲ساعته باید فرمان foreground واقعاً روشن بماند و Coverage/Gapها بررسی شوند. افق Forecast ۴۵ دقیقه است و با دوره ارزیابی ۴۸ ساعت تعارض ندارد.

Milestone 7: جمع‌آوری آینده‌نگر واقعی بیشتر، Quoteهای موعد با تلورانس ثابت، ارزیابی جفت‌شده/Block-aware روی نمادها، هزینه تأییدشده، Coverage خبر، بررسی اختلاف Shadow/Replay و سپس پژوهش تصمیم‌گیری؛ بدون انتخاب مدل با Test یا تغییر خودکار Risk/Champion. اگر Quote موعد از دست برود، بازسازی یا Interpolation مجاز نیست. Replay فعلی روی ورودی ذخیره‌شدهٔ تصمیم است، نه بازاجرای Bit-exact آموزش GPU.

محدودیت نسخه‌بندی: سه چرخه محدود اولیه هنگام توسعه اجرا شدند و Hash کل سورس Pipeline را ثبت نکردند؛ Hash مدل، ورودی و رسیدهای واقعی آن‌ها محفوظ است. آن‌ها را مطالعه ثابت ۴۸ساعته با یک نسخه استراتژی محسوب نکنید. نسخه نهایی Hash سورس LF-normalized را به Session و پیش‌بینی مقید می‌کند و تغییر سورس در اجرای مداوم را متوقف می‌سازد. برای مطالعه رسمی بعدی، Session تازه بسازید.

## ۶. ورودی لازم و بازتولید

مجوز تازه برای پژوهش لازم نیست. برای نتیجه اقتصادی هزینه واقعی قابل تأیید و شواهد آینده لازم است. LIVE همچنان HARD_DISABLED است و این مرحله مجوز معامله واقعی نیست. ادامه چندروزه به اجرای پایدار foreground توسط کاربر/محیط میزبان نیاز دارد؛ برنامه خودکار یا پنجره پنهان دائمی ایجاد نشده است.

از ریشه پروژه در PowerShell:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
conda run --no-capture-output -n shbk python -m pytest -q --junitxml=reports/m6_pytest.xml
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_forward_watch collect --top 2 --max-cycles 1 --shadow
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_forward_watch collect --top 2 --shadow
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_forward_watch status
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_forward_watch reconcile
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m6_report
```

فرمان دوم اجرای محدود است؛ فرمان سوم foreground تا پایان Deadline اولیه ادامه می‌دهد و با Ctrl+C قابل توقف/Resume است. حذف `--shadow` برای Session تازه، مشاهده-only است؛ قرارداد Session موجود را بی‌صدا عوض نکنید و از `--session-dir` جدا استفاده کنید. `--no-sync` مستقل از Shadow، Sync را در Observer و Agent خاموش می‌کند و داده نامعتبر همچنان کنار گذاشته می‌شود. برای ۷۲ ساعت از Session جدید و `--hours 72` استفاده کنید. API Key یا فایل رمز لازم نیست.
