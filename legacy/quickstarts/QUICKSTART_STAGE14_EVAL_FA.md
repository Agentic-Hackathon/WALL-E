# راهنمای Stage 14 — ارزیابی مدل‌های ذخیره‌شده بدون آموزش

روی شاخه `integration/atlas-paired-challenger-v2` در commit `b8af77f`، ZIP پچ را در پوشه پروژه استخراج کرده و فرمان زیر را اجرا کنید:

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage14_eval.sh
```

سپس پوشه **واقعی** اجرای Stage13 خودتان را مشخص کنید. مطابق خروجی شما:

```bash
python -m wallex_bot.atlas_cli challenger-evaluate --mode BACKTEST \
 --checkpoint-dir research_challengers/stage13_paired_v2/20261022T113152Z_a71cb63c
```

این مسیر نسبت به `atlas_store` است. فرمان هیچ فایل خروجی یا دیتابیسی نمی‌سازد؛ گزارش را به‌صورت JSON در ترمینال چاپ می‌کند. اولویت تفسیر با `v2_only_extra_held_out_validation` (مقایسه V2_COMMON و V2_EXPANDED روی نمونه‌های USDT) و `shared_epoch_selected_validation.per_symbol` است.

اگر `FAIL_CLOSED_SAVED_RUN_OR_PROVENANCE_MISMATCH` دریافت کردید، فایلی را بازنویسی یا از روی دیتا دوباره پر نکنید. این پیام ممکن است از پیشروی آرشیو یا تفاوت زمان ثبت Quote نسبت به اجرای تاریخی ناشی شده باشد. باید با فهرست فایل‌های SHA-256، Split و checkpoint واقعی همان اجرا بررسی شود.

### محدودیت‌ها

انجام تحلیل OOS مالی، معاملات واقعی، قیمت‌گذاری Fill و promotion در محدوده این ابزار نیست. معیارهای q50 direction و pinball به‌تنهایی بیانگر سودآوری نیستند. استفاده از حالت `--mode LIVE` مسدود است.
