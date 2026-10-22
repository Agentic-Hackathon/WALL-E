# گزارش واقعی Milestone 5 — Wallex Atlas

## نتیجه و حدود تکمیل

کد پژوهش، آموزش واجد شرایط، Calibration مستقل، Resume و Replay پیاده‌سازی و اجرا شدند. هدف اصلی ۴۸/۷۲ ساعت هنوز از نظر داده قابل آموزش نیست؛ این مرحله به معنی اثبات پیش‌بینی بلندمدت یا مزیت اقتصادی نیست. نتیجه: `NO_VERIFIED_ECONOMIC_EDGE`.

شاخه: `integration/atlas-milestone-5-deep-forecasting`؛ مبنا: `905047a`؛ Commit پیاده‌سازی هنگام تولید گزارش: `9ac101a6f99442451796501aa4affd1c4cd05af3`. Commit تحویل گزارش جدا ثبت می‌شود.

مسیر نسخه‌دار واقعی: `D:\Hackaton\Wallex\wallex_agent_v3\atlas_store\research_challengers\milestone5\m5_20261022_frozen_v1`. هیچ Checkpoint قدیمی، حافظه، داده یا حسابی پاک یا جایگزین نشد. وزن‌ها/دیتاست‌ها در Git نیستند و باید همراه این مسیر نگه‌داری شوند.

## ۱. منبع، لایسنس و پیاده‌سازی

خواندن archive و SHA، DataSyncManager، V1/V2/V3، دو Backbone موجود، BACKTEST memory و NewsStore بازاستفاده شدند. هیچ کد Champion، RiskGate، Broker یا Watch تغییر نکرد. پیاده‌سازی چهار Split، آموزش، Head مرتب، Calibration، ارزیابی و گزارش مستقل نوشته شد.

مرجع DLinear: `cure-lab/LTSF-Linear`، commit `0c113668a3b88c4c4ee586b8c5ec3e539c4de5a6`، Apache-2.0؛ LICENSE و `models/DLinear.py` بررسی شدند. کدی کپی نشد. `DLinear_ridge` تطبیق مستقل trend/residual با میانگین متحرک ۲۵نقطه‌ای، هدف scalar log-return و Ridge است؛ بازتولید آموزش SGD/پیش‌بینی چندگامی مقاله نیست. جزئیات در `third_party/SOURCES.md`.

## ۲. داده، فایل‌ها و اجرای واقعی

چهار Chunk واقعی 60m از API عمومی، با DataSync موجود، Retry صفر، Cache Hit صفر و خطای صفر دریافت شد؛ هفت Window برنامه‌ریزی‌شده در سقف محدود این اجرا باقی ماند. درخواست احرازهویت‌شده یا سفارش وجود نداشت. ریز شواهد در `m5_data_sync.json`.

| تایم‌فریم | افق ساعت | نمونه مشترک | وضعیت |
|---|---:|---:|---|
| 15 | 0.75 | 671 | ELIGIBLE_RETROSPECTIVE_RESEARCH |
| 60 | 48 | 0 | INSUFFICIENT_REAL_TRAINING_HISTORY |
| 60 | 72 | 0 | INSUFFICIENT_REAL_TRAINING_HISTORY |
| 1D | 48 | 0 | INSUFFICIENT_REAL_TRAINING_HISTORY |
| 1D | 72 | 0 | INSUFFICIENT_REAL_TRAINING_HISTORY |
| 15 | 48 | 0 | INSUFFICIENT_REAL_TRAINING_HISTORY |
| 15 | 72 | 0 | INSUFFICIENT_REAL_TRAINING_HISTORY |

در هیچ‌یک از هشت بازار منتخب، افق ۴۸/۷۲ ساعت با Context و Warmup لازم قابل آموزش نبود؛ بنابراین Walk-forward این افق‌ها اجرا نشد. طول قطعه ساعتی حداکثر ۸۰ بار و روزانه فقط چند بار است. دانلود بلندمدت غیرضروری انجام نشد.

۴۵دقیقه: 671 نمونه واقعی مشترک؛ Splitها: `{'train': 341, 'validation': 70, 'calibration': 77, 'test': 99}`؛ 84 نمونه Purge شد. Embargo یک کندل ۹۰۰ثانیه‌ای؛ مرزها از زمان‌ها و نه بازده ساخته شدند. هفت بازار مشترک: PEPE/BTC/PUMP/ETH/USOON/BNB/DOGE با کوت TMN؛ USDT پنجره V1 مشترک معتبر نداشت.

تمام قیمت‌ها از فایل‌های SHA-تأییدشدهٔ واقعی‌اند؛ Gapها به قطعات جدا تقسیم شدند. زمان Candle زمان بازشدن است و Cutoff پایان کندل. برچسب log(close_future/close_now) است، نه بازده قابل اجرای Bid/Ask. Legacy receipt نامعلوم، null باقی مانده و زمان مشاهده با زمان بسته‌شدن جعل نشده است. آزمون فعلی retrospective است، نه PIT آینده‌نگر. انتخاب Universe با Turnover فعلی، سوگیری انتخاب تاریخی بالقوه دارد.

گروه A: پنج ستون OHLCV تبدیل‌شده + ۱۶ ویژگی V1؛ B: همان Core + V2؛ C: چهار ویژگی منتخب `ema50_ratio,hma20_ratio,bb_width20,trend_persistence20` اضافه شد (جمع ۲۵). روی مجموعه مشترک A/B دقیقاً یکسان‌اند و B آموزش تکراری مستقل ندارد. D: صفر پنجره ساعتی PIT واجد شرایط؛ E: فقط ۸۳ نمونه Book مشترک؛ F/G: صفر نمونه خبری PIT. فقدان اختیاری Core را متوقف نکرد و با صفر جعلی پر نشد. این اجرا ادعای انتخاب بهینه از هر ۵۲ ویژگی ندارد.

ماژول‌ها: `atlas_m5_data.py`، `atlas_m5_models.py`، `atlas_m5_baselines.py`، `atlas_m5_research.py`، `atlas_m5_inference.py`، `atlas_m5_report.py`؛ تست: `test_milestone5_research_real_only.py`. تمام خروجی‌های الزامی در reports تولید شده‌اند.

## آموزش و نتایج

۱۸ آموزش اصلی، 316 Epoch واقعی، Seedهای 17/29/43؛ RTX 4080 SUPER، BF16، AdamW، ReduceLROnPlateau، Clip=1، سقف ۱۲۰ Epoch، Patience=15 و min_delta=1e-5. همه به Early Stopping رسیدند؛ بهترین Epoch اغلب ۱ تا ۴ بود: نشانه کمبود داده/Overfitting، نه توجیه ادامه مصنوعی تا ۱۲۰. مجموع زمان آموزش اصلی 96.4 ثانیه است؛ اندازه نمونه کوچک است.

| آزمایش | Epoch توقف | بهترین Epoch | GPU peak MiB |
|---|---:|---:|---:|
| A_itransformer_ordered_17 | 17 | 2 | 138.9 |
| A_itransformer_ordered_29 | 16 | 1 | 138.9 |
| A_itransformer_ordered_43 | 17 | 2 | 138.9 |
| A_patchtst_ordered_17 | 18 | 3 | 316.9 |
| A_patchtst_ordered_29 | 18 | 3 | 316.2 |
| A_patchtst_ordered_43 | 16 | 1 | 316.9 |
| C_itransformer_ordered_17 | 16 | 1 | 151.2 |
| C_itransformer_ordered_29 | 26 | 11 | 151.2 |
| C_itransformer_ordered_43 | 17 | 2 | 151.2 |
| C_patchtst_ordered_17 | 19 | 4 | 368.8 |
| C_patchtst_ordered_29 | 16 | 1 | 368.8 |
| C_patchtst_ordered_43 | 16 | 1 | 368.8 |
| A_itransformer_raw_17 | 18 | 3 | 138.9 |
| A_itransformer_raw_29 | 18 | 3 | 138.9 |
| A_itransformer_raw_43 | 16 | 1 | 138.9 |
| A_itransformer_penalty_17 | 16 | 1 | 138.9 |
| A_itransformer_penalty_29 | 18 | 3 | 138.9 |
| A_itransformer_penalty_43 | 18 | 3 | 138.9 |

| گروه/مدل/Head | میانگین Pinball تست | انحراف معیار Seed |
|---|---:|---:|
| A/patchtst/ordered | 0.00118844 | 0.00006759 |
| C/patchtst/ordered | 0.00120547 | 0.00005310 |
| A/itransformer/ordered | 0.00894527 | 0.01160132 |
| A/itransformer/raw | 0.00260864 | 0.00080351 |
| C/itransformer/ordered | 0.00227952 | 0.00123910 |
| A/itransformer/penalty | 0.00267993 | 0.00117278 |

| Baseline | Pinball تست خام | Pinball پس از Calibration |
|---|---:|---:|
| zero | 0.00154568 | 0.00117117 |
| historical_mean | 0.00117235 | 0.00117117 |
| historical_median | 0.00117235 | 0.00117117 |
| momentum | 0.00117129 | 0.00117004 |
| volatility_scaled | 0.00117042 | 0.00114583 |
| DLinear_ridge | 0.00130961 | 0.00129665 |
| LightGBM_quantile | 0.00112829 | 0.00116346 |

انتخاب پژوهشی فقط با میانگین Validation و سپس بهترین Seed همان بازو: `A_patchtst_ordered_17`، Checkpoint SHA `4f422406f03d57a7d8c0ca7891695a1057821c2d4083a197f0e4b0dca28a5fad`؛ بهترین Epoch 3. این انتخاب هیچ Promotion ایجاد نکرد. Pinball خام آن 0.00114500 و پس از Calibration 0.00118157 است.

میانگین PatchTST-A از LightGBM خام بهتر نیست؛ افزودن V3 نیز بهبود پایدار نشان نداد. iTransformer در Seed 43 بسیار ناپایدار بود. بنابراین هیچ پیچیدگی تازه‌ای وارد تصمیم عملیاتی نشد. مقایسه جفت‌شده روی بلوک زمانی و همه نتایج نمادها ثبت شده، ولی با تعداد بلوک کم و تعدد مقایسه‌ها ادعای معناداری آماری نمی‌کنیم.

Head مرتب Crossing را به صفر رساند؛ Penalty به‌تنهایی تضمین نکرد. برای مدل منتخب پس از Calibration: پوشش پایین q10=0.9192، پوشش بالای q90=0.9697، پوشش بازه=0.8889 در برابر هدف ۰٫۸، عرض=0.014748 و خطای Calibration=0.068350. کالیبراسیون Pinball را بدتر کرد؛ مرتب بودن معادل کالیبراسیون صحیح نیست. ۷۷ نمونه Calibration هم‌بسته، شواهد بلندمدت کافی نیست.

اخبار: `INSUFFICIENT_PIT_NEWS_VALIDATION`؛ هیچ برتری News گزارش نمی‌شود و محدودیت FinBERT CC-BY-NC-SA-4.0 پابرجاست. Smoke واقعی LangGraph، حافظه BACKTEST، خبر در Cutoff واقعی و Replay را به هم وصل کرد؛ این گراف پژوهشی جداست، نه اجرای گراف معاملاتی SHADOW. هیچ LLM خارجی یا Broker فراخوانی نشد و Hash منطقی News/Memory/Shadow قبل و بعد برابر بود.

Forward ledger فقط در research_challengers است؛ Forecast گذشته را رد می‌کند، ورودی ۴۸/۷۲ واقعی آینده‌نگر می‌خواهد و reconciliation فقط Quote واقعی hash-تأییدشده را جفت می‌کند. اکنون صفر رکورد/Outcome دارد؛ گذشت ۴۸/۷۲ ساعت ادعا نشده است. بازده Mid، Fill یا PnL نیست و هزینه تأییدنشده null می‌ماند.

## ۳. تست‌ها

اجرای کامل: **190 passed, 5 skipped، 0 failed، 0 errors**؛ Baseline: 174 passed, 5 skipped. هیچ تست قدیمی حذف نشد. JUnit واقعی و JSON نتایج نگه‌داری شدند.

۱۶ تست جدید شامل Split/Purge، عدم نگاه به آینده روی Prefix واقعی، SHA Manifest، عدم Imputation، ترتیب کوانتایل، جداسازی Calibration، رفتار Early Stopping، بازیابی وزن بهترین Epoch، قطع واقعی پس از Epoch ۱ و Resume، سه Seed واقعی، منع Promotion، ممنوعیت اختلاط Dataset در Run و ایزولاسیون Smoke است. Resume بازوی A/iTransformer/17 منحنی Validation اجرای بدون قطع را با تلورانس ثبت‌شده بازتولید کرد. آزمایش‌های Pilot، یک شکست نام‌گذاری معماری و Resume در Registry جدا ثبت شده‌اند تا تعداد تلاش‌ها پنهان نماند.

## ۴. این تغییر چه چیزی را اثبات نمی‌کند؟

سودآوری، مزیت بعد از کارمزد واقعی، بازده قابل اجرا، Drawdown/Turnover سبد، اعتبار Live، عملکرد ۴۸/۷۲ ساعت، برتری آماری مدل عمیق، اثر خبر یا بازتولید مقاله DLinear اثبات نشده‌اند. هزینه واقعی/Book آینده کافی نیست؛ PnL و Drawdown ساختگی محاسبه نشده و حساسیت q10 صرفاً بر هزینه فرضی روی برچسب Close گزارش شده است. Cash/TMN صفر تعریف حسابداری است، نه نتیجه معامله؛ Buy-and-Hold قابل اجرا بدون شواهد کافی null است.

## ۵. اثر بر سامانه و موارد باز

قابلیت ممیزی، بازتولید، اعتبارسنجی زمانی، کنترل Quantile و خطایابی مدل بهتر شده است؛ امتیاز عددی بارم یا بهبود اقتصادی ادعا نمی‌شود. Sourceهای محافظت‌شده با مبنای 905047a بدون Diff هستند. موارد باز: جمع‌آوری پیوسته واقعی برای Context+Label+Split افق بلند، Receipt کامل PIT، دفتر سفارش هم‌زمان، کارمزد تأییدشده و Walk-forward چندرژیمی. Core و مدل‌های قبلی مستقل باقی مانده‌اند.

## ۶. ورودی لازم از کاربر

برای ادامه پژوهش Core تأیید تازه لازم نیست؛ زمان واقعی و داده بیشتر لازم است. برای ادعای اقتصادی، جدول کارمزد قابل تأیید و دفتر سفارش آینده لازم است. این درخواست هیچ مجوز LIVE نمی‌دهد؛ پکیج/بازار/هزینه و مجوز صریح اجرای واقعی همچنان لازم‌اند.

## فرمان‌های بازتولید (از ریشه پروژه، PowerShell)

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
conda run --no-capture-output -n shbk python -m pytest -q --junitxml=reports/m5_pytest.xml
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_research run
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_research run --dataset-key 60_48 --reports reports/m5_48h
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_research run --run-directory atlas_store\research_challengers\milestone5\m5_20261022_frozen_v1
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_inference replay --run-directory atlas_store\research_challengers\milestone5\m5_20261022_frozen_v1
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_inference forward-reconcile --run-directory atlas_store\research_challengers\milestone5\m5_20261022_frozen_v1
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_report --run-directory atlas_store\research_challengers\milestone5\m5_20261022_frozen_v1
```

فرمان بدون run-directory پوشه تازه می‌سازد؛ دادهٔ جاری ممکن است تغییر کرده باشد. فرمان روی پوشه منجمد، نتایج تکمیل‌شده را بازاستفاده می‌کند و آموزش ناقص را فقط با Provenance یکسان Resume می‌کند. اجرای اولیه تست Resume یک آزمایش واقعی جدا می‌سازد؛ تکرارها شواهد تکمیل‌شده را بررسی می‌کنند.
