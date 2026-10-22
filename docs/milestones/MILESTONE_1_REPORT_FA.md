# گزارش Milestone 1 — ممیزی و حفاظت وضعیت

## Problem

پروژه تا Stage 14 توسعه یافته بود، اما پیش از هر توسعهٔ جدید به یک تصویر بازتولیدپذیر از معماری، محیط اجرا، وضعیت Git، داده/مدل‌های موجود، و مرزهای ایمنی نیاز داشت. بدون آن، تغییرات بعدی می‌توانستند ناخواسته محیط اشتباه را مبنا بگیرند، artifactهای کاربر را آلوده کنند یا شواهد پژوهشی را به‌عنوان سودآوری تعبیر کنند.

## Root Cause

محیط Python پیش‌فرض با محیط معتبر پروژه متفاوت است و ABI ناسازگار NumPy دارد. همچنین دادهٔ عملیاتی، watch و checkpointها وضعیت پویا دارند؛ در کنار آن، شواهد Stage 13/14 و forward فعلی هنوز edge اقتصادیِ قابل اتکا نشان نمی‌دهند.

## Implemented Changes

- نقشهٔ معماری، جریان داده و نقاط veto در `ARCHITECTURE_AUDIT_FA.md` ثبت شد.
- snapshot فقط‌خواندنی محیط، GPU، Git، store و قرارداد ایمنی در `environment_audit.json` ثبت شد.
- baseline تست معتبر و تفاوت محیط پیش‌فرض در `test_baseline.json` ثبت شد.
- هیچ ماژول تولیدی، ریسک، broker، مدل، checkpoint، حافظه، دادهٔ بازار یا تنظیم LIVE تغییر نکرد.

## Modified Files

- `docs/ARCHITECTURE_AUDIT_FA.md`
- `reports/environment_audit.json`
- `reports/test_baseline.json`
- `docs/milestones/MILESTONE_1_REPORT_FA.md`

## Tests

فرمان اجراشده:

```powershell
conda run -n shbk python -m pytest -q
```

نتیجه: `139 passed, 5 skipped` در ۵٫۴۷ ثانیه. تعداد skipها همان خروجی pytest است و علت آن‌ها حدس زده نشده است. اجرای همان تست در Python پیش‌فرض به‌علت ناسازگاری ABI وابستگی‌های علمی در مرحلهٔ collection نامعتبر است.

## Real Data Used

فقط داده‌های موجود و واقعیِ محلی به‌صورت خواندنی بررسی شد: catalog بایگانی (`۴۶۹` دارایی، `۳۷۳` spot، `۱۸۷` spot/TMN، `۳٬۷۶۰` chunk کامل)، گزارش readiness، دفتر forward و checkpoint ذخیره‌شدهٔ Stage 13. هیچ کندل، خبر، quote، سفارش یا fill ساخته، تزریق یا بازنویسی نشد. Stage 14 با ۱۸۵ hash منبع و hash split، snapshot ذخیره‌شدهٔ Stage 13 را بازسازی کرد.

## Experimental Results

- ارزیابی ذخیره‌شدهٔ challenger نشان می‌دهد recipe توسعه‌یافتهٔ V2 در shared validation نسبت به common raw pinball به اندازهٔ `+0.010729191` بدتر است و در held-out اضافی نیز `+0.010364116` بدتر است؛ بنابراین promotion انجام نشده است.
- دفتر forward: ۱۳۳ outcome امتیازدهی‌شده در span حدود ۵٫۸۲۴ ساعت دارد؛ میانگین net ask→future-bid منفی و نرخ مثبت حدود ۲۷٫۸٪ است.
- گزارش edge-triage در ۱۵۱ forecast معتبر، عبور Q10 از هزینه را صفر ثبت کرده است.

این نتایج فقط شکست معیار پذیرش اقتصادی فعلی را نشان می‌دهند؛ نه اینکه هیچ روش آینده‌ای سودآور نخواهد شد.

## Limitations

- پوشش forward پیوستهٔ ۴۸ ساعته وجود ندارد.
- target آموزش close-to-close با target ارزیابی quote-to-quote یکسان نیست.
- ۹۲ خبر واقعی موجود هستند، اما هیچ‌کدام sentiment ثبت‌شده و هیچ ورودی خبری در champion فعلی ندارد.
- صحت کارمزد واقعی، market allowlist و الزامات package مسابقه هنوز ورودی تأییدشده ندارند.
- `pip check` در محیط مشترک تضادهای نامرتبط گزارش می‌دهد؛ محیط اصلاح نشد.

## Risks

- تفسیر متریک مدل یا تعداد معامله به‌عنوان سود، خطر اصلی است؛ معیار معتبر فقط net OOS پس از هزینهٔ تأییدشده و drawdown کنترل‌شده است.
- watch موجود ممکن است `atlas_store` را تغییر دهد؛ مقادیر این گزارش snapshot هستند.
- یکپارچگی watch با مسیر کامل LangGraph/portfolio هنوز کامل نیست.
- LIVE باید همچنان سخت غیرفعال بماند؛ `WallexLiveBroker` submit transport ندارد.

## Commit Hash

`PENDING_FIRST_AUDIT_COMMIT` — hash دقیق در commit تکمیلی همین milestone ثبت می‌شود تا سند به hash واقعی و تغییرناپذیر اشاره کند.

## Next Actions

1. Milestone 2 را با قرارداد داده و کیفیت PIT شروع کنید، بدون دست‌زدن به مسیر LIVE.
2. قرارداد target و timestamp آموزش/forward را یکسان کنید.
3. فقط پس از جمع‌آوری واقعی و پیوستهٔ شواهد، challenger یا feature جدید را با baseline ساده مقایسه کنید.
