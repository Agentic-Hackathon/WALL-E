# ممیزی معماری Wallex Atlas — Milestone 1

**زمان مشاهده:** ۲۰۲۶-۱۰-۲۲ (UTC)  
**نقطهٔ شروع کد:** `af7b9bf` (`baseline-v3.4`)  
**شاخهٔ ممیزی:** `integration/atlas-milestone-1-audit`

## دامنه و حکم ایمنی

این سند یک ممیزی خواندنی است، نه تأیید سودآوری یا آمادگی معاملهٔ واقعی. وضعیت اجرای واقعی عمداً `HARD_DISABLED` است: هیچ مسیر ارسال سفارش به صرافی پیاده‌سازی یا مجاز نشده و فقط اسپاتِ تومان در لایه‌های پژوهش و Shadow/Paper دیده می‌شود. کلید API در این ممیزی خوانده یا استفاده نشده است.

```text
Wallex public REST / WebSocket
              |
              v
 market.py / wallex_api.py  -->  atlas_archive.Lake (SQLite + gzip + SHA-256)
              |                              |
              |                              +--> atlas_signals / feature health / recipe audit
              |                              +--> atlas_deep / challenger V2 / validation
              |                              +--> atlas_news (PIT availability guard)
              v
 atlas_agent LangGraph: context -> market -> technical -> news -> deep forecast
              |                                      |
              +--> deterministic atlas_risk.RiskGate <-+  (LLM has advisory-only role)
                               |
                               v
             ShadowBroker -> PaperAccount (hash-chained hypothetical ledger)
                               |
        forward ledger / context-memory / replay / operational reports

LIVE path: blocked by atlas_mode and WallexLiveBroker; no submit transport exists.
```

## اجزای اصلی و مسئولیت‌ها

| لایه | ماژول‌ها | مسئولیت و کنترل |
|---|---|---|
| دریافت و بایگانی | `market.py`, `wallex_api.py`, `atlas_archive.py`, `atlas_stream.py` | دریافت عمومی/خواندنی، chunkهای هش‌شده، تشخیص شکاف و دادهٔ کتاب سفارش؛ نه ارسال سفارش |
| سیگنال و داده | `atlas_signals.py`, `atlas_feature_health.py`, `atlas_feature_recipe.py` | ویژگی‌های فنی، کنترل non-finite و دستور ساخت ویژگی‌های پژوهشی |
| پیش‌بینی | `atlas_deep.py`, `atlas_challenger_v2.py` | iTransformer/PatchTST کوانتایلی، split با purge، provenance و challenger جدا از champion |
| خبر | `atlas_news.py` | نگهداری زمان در دسترس‌شدن خبر و جلوگیری از نشت آینده؛ امتیازدهی FinBERT در صورت موجودبودن |
| عامل و حافظه | `atlas_agent.py`, `atlas_context.py`, `atlas_memory.py`, `atlas_rationale.py` | LangGraph، بستهٔ شواهد هش‌شده، حافظهٔ PIT و دلیل‌پردازی محلی مشاوره‌ای |
| کنترل قطعی | `atlas_risk.py`, `atlas_mode.py` | تنها دروازهٔ سفارش، پوشش هزینه با Q10، سقف‌ها و قرارداد سخت اجرای حالت‌ها |
| اجرای فرضی | `atlas_broker.py`, `atlas_shadow.py`, `atlas_liquidation.py` | intent idempotent، ShadowBroker، دفتر PaperAccount و liquidation کاغذی؛ LiveBroker پوستهٔ غیرفعال |
| ارزیابی و عملیات | `atlas_validation.py`, `atlas_forward.py`, `atlas_replay.py`, `atlas_operational.py`, `atlas_edge_triage.py`, `atlas_readiness.py` | DSR/PBO و baselineها، ثبت پیش‌بینی و quoteهای آینده، بازپخش تصمیم و گزارش قابلیت اتکا |
| چرخهٔ زمان‌دار | `atlas_watch.py` | بایگانی/مشتق‌سازی/خبر/بستهٔ زمینه و shadow cycle در foreground؛ خاتمهٔ paper از liquidation عبور می‌کند |

## قراردادهای حالت و CLI

`atlas_mode.py` سه حالت دارد:

| حالت | اثر مجاز |
|---|---|
| `BACKTEST` | زمینهٔ تولیدی فقط‌خواندنی است و رخداد عملیاتی برای جلوگیری از leakage نوشته نمی‌شود |
| `SHADOW` | حافظه و اقدام فرضیِ risk-gated مجاز است؛ دارایی و سفارش واقعی تغییر نمی‌کند |
| `LIVE` | همیشه با `LIVE_EXECUTION_HARD_DISABLED_NO_AUTHORIZATION` متوقف می‌شود |

فرمان‌های در دسترس از `atlas_cli.py` شامل دریافت/بایگانی (`discover`, `archive-all`, `capture-live`)، مدل و benchmark (`train-deep`, `benchmark`, `validate`)، عامل و shadow (`agent-cycle`, `shadow-cycle`, `watch`)، حساب و broker (`account-audit`, `broker-status`, `liquidate-paper`)، و ممیزی (`audit-v3`, `forward-report`, `operations-report`, `edge-triage`, `challenger-evaluate`) است. `mode-status` در محیط صحیح تأیید کرد که `real_exchange_order_submission=false` و `no_live_orders=true` است.

نکتهٔ UX: همهٔ فرمان‌های تشخیصی `--mode` نمی‌پذیرند؛ برای نمونه `feature-health --mode BACKTEST` عمداً خطای «explicit mode not applicable» می‌دهد. این یک ناسازگاری رابط است، نه اثبات خرابی داده یا مدل.

## موجودی خواندنی داده و مدل

مشاهدهٔ فقط‌خواندنی از `atlas_store` در زمان ممیزی:

| مورد | مقدار مشاهده‌شده |
|---|---:|
| دارایی‌ها | ۴۶۹ |
| بازارهای spot | ۳۷۳ |
| بازارهای spot/TMN | ۱۸۷ |
| chunkهای کامل | ۳٬۷۶۰ |
| کندل‌ها در وضعیت CLI | ۳۷۴٬۲۴۹ |
| تفکیک chunk برحسب resolution | `1`: ۱٬۸۶۰، `15`: ۳۱۷، `60`: ۱٬۵۸۳ |
| اندازهٔ بایگانی | ۲۴۸٬۸۷۶٬۳۵۴ بایت در ۳٬۸۰۹ فایل |

این اعداد snapshot هستند؛ یک watch موجود می‌تواند با چرخه‌های خودش store را تغییر دهد. ممیزی هیچ watch را آغاز، متوقف یا تغییر نداد و هیچ فایل داده‌ای را حذف یا بازنویسی نکرد.

گزارش readiness champion فعال را `patchtst_15_h3_20261022T060722Z_ca057cc3.pt` با ۱٬۱۸۹ نمونهٔ آموزش و ۵۱۱ نمونهٔ اعتبارسنجی معرفی می‌کند؛ پنجرهٔ مؤثر اعتبارسنجی هشت ساعت است. این گزارش صریحاً می‌گوید OOS اقتصادی اثبات نشده است.

Stage 14 با checkpoint ذخیره‌شدهٔ Stage 13، ۱۸۵ hash منبع و hash split را بازسازی و تأیید کرد. در shared validation، recipe توسعه‌یافتهٔ V2 نسبت به common raw pinball بدتر بود (`+0.010729191`) و در held-out اضافی نیز بدتر بود (`+0.010364116`). بنابراین هیچ promotionی انجام نشده و نباید انجام شود.

## محیط، تست و قابلیت بازتولید

محیط معتبر پروژه `conda run -n shbk python ...` است: Python 3.12.3، NumPy 2.3.5، PyTorch 2.11.0+cu128، CUDA 12.8 و یک RTX 4080 SUPER. تست پایه در این محیط `139 passed, 5 skipped` در ۵٫۴۷ ثانیه است.

Python پیش‌فرض سیستم (CPU-only، NumPy 2.2.6) با binaryهای SciPy/sklearn ناسازگار است و در collection تست شکست می‌خورد؛ این یک خطای محیط انتخاب‌شده است، نه regression اثبات‌شدهٔ Atlas. `pip check` محیط `shbk` نیز تضادهای packageهای سراسریِ نامرتبط را گزارش می‌کند؛ در این milestone هیچ محیط مشترکی تغییر داده نشده است.

## شواهد عملیاتی و شکاف‌های اولویت‌دار

| اولویت | شکاف مشاهده‌شده | شاهد | نتیجهٔ لازم |
|---|---|---|---|
| P0 | edge اقتصادی تأیید نشده | ۱۳۳ outcome پیش‌نگر، میانگین net ask→future-bid منفی و تنها ۲۷٫۸٪ مثبت؛ Q10 از هزینه در ۰ مورد عبور کرد | تا داده و هزینهٔ واقعیِ کافی، فقط پژوهش/Shadow |
| P0 | پوشش پیش‌نگر ناکافی | span فقط ۵٫۸۲۴ ساعت، نه ۴۸ ساعت پیوسته | پروتکل جمع‌آوری واقعی و پایدار، بدون ساخت داده |
| P0 | ناهماهنگی target/timing | آموزش close-to-close و ارزیابی forward quote-to-quote | قبل از هر promotion، قرارداد target یکسان و PIT بسازید |
| P1 | پوشش و تازگی داده محدود | فقط ۴۲ بازار ۱۵ دقیقهٔ verified و ۸ بازار تازه در گزارش readiness | ماتریس کیفیت داده و allowlist پژوهشی بسازید |
| P1 | خبر در مدل وارد نشده | ۹۲ مقالهٔ واقعی، همه بدون sentiment؛ خطاهای timeout/connection ثبت شده | ingestion مقاوم و ویژگی PITِ قابل audit، فقط پس از دادهٔ واقعی کافی |
| P1 | watch با گراف کامل یکپارچه نیست | watch مستقیماً shadow cycle را فرا می‌خواند، نه مسیر کامل `atlas_agent` | پیش از تصمیم‌گیری خودکار، مسیر یگانهٔ گراف/portfolio طراحی شود |
| P1 | challenger V2 برتر نیست | Stage 14 recipe توسعه‌یافته را رد می‌کند و پوشش quantile ضعیف است | V2 خارج از مسیر تصمیم باقی بماند |
| P2 | وابستگی‌های محیط مشترک نویز دارند | `pip check` نامرتبط ناموفق؛ محیط پایه ABI ناسازگار | lockfile/محیط ایزوله برای بازتولید بسازید |
| P2 | رابط mode نامتوازن است | برخی diagnostics `--mode` را نمی‌پذیرند | CLI contract را در milestoneهای بعدی همسان کنید |

در گزارش عملیات، ۲۸ mark-to-market تازه و ۱۸۴ رد «insufficient risk adjusted edge» دیده شد؛ ۷۵ رد نیز `Q10_DOES_NOT_COVER_OBSERVED_COSTS` بود. این‌ها نشانهٔ فعال‌بودن veto هستند، نه سود یا اعتبار پیش‌بینی. هیچ سفارش صرافی، fill واقعی یا PnL محقق‌شده مشاهده نشد.

## حفظ وضعیت و مرزهای ممیزی

Commitهای Stage 1 تا 14 در تاریخچه حضور دارند و Stageهای 13 و 14 به‌طور خاص با run ذخیره‌شده بازبینی شدند. وضعیت کاری آغاز ممیزی هیچ تغییر tracked نداشت، اما artifactهای untracked کاربر (patch/ZIP/راهنما) وجود داشتند. این‌ها حفظ شده‌اند و در commit ممیزی وارد نمی‌شوند.

این ممیزی سودآوری، کیفیت کل بازارها، صحت کارمزد واقعی، مجازبودن package/marketهای مسابقه، یا آماده‌بودن برای LIVE را اثبات نمی‌کند. تنها اثبات می‌کند که snapshot بررسی‌شده قراردادهای ایمنی و baseline تست ذکرشده را در محیط `shbk` دارد و شواهد فعلی برای promotion اقتصادی کافی نیست.
