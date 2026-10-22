# راهنمای نصب و اجرای Stage 13 — Challenger V2 مستقل

ابتدا Watch را در مرز چرخه متوقف کنید تا عملیات آموزشی با فرآیند گردآوری داده تداخل عملیاتی نداشته باشد. بسته PATCH را در ریشه پروژه استخراج کنید؛ **نسخه FULL را روی پروژه موجود کپی نکنید**.

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage13_challenger.sh
```

در صورت موفقیت، شاخه `integration/atlas-paired-challenger-v2` ساخته می‌شود. خروجی اولیه فقط ممیزی نمونه‌ها و Split است:

```bash
python -m wallex_bot.atlas_cli challenger-preflight --mode BACKTEST --top 8 --hours 24
```

اگر وضعیت `RESEARCH_TRAINING_ELIGIBLE_NOT_TRADING_APPROVED` و تعداد نمونه‌ها مناسب بود، برای **آموزش پژوهشی و غیرمعاملاتی**:

```bash
python -m wallex_bot.atlas_cli train-challenger-v2 --mode BACKTEST --model patchtst --epochs 6 --top 8 --hours 24
```

این دستور سه آزمایش پیاپی از صفر انجام می‌دهد و ممکن است بسته به GPU و آرشیو زمان‌بر باشد. به‌صورت پیش‌فرض با `--model both` آموزش داده نمی‌شود؛ نام معماری باید مشخص باشد. خروجی در پوشه‌ای خارج از `atlas_store/models` ثبت می‌شود و `active_champion.json` تغییر نمی‌کند.

فیلدهای گزارش اولیه: `common_train_samples`، `common_validation_samples`، `v2_additional_train_samples`، `v2_additional_validation_samples_HELD_OUT_NOT_TRAINED`، `split_sha256` و `validation_hours_effective`.

در گزارش آموزش، سه `validation_loss` را مقایسه کنید. چون پنجره‌های مشترک V1 و V2 قبل از رفع NaN یکسان‌اند، انتظار داریم تفاوت دو بازوی COMMON نزدیک به صفر باشد؛ بازوی EXPANDED فقط آزمایش اثر نمونه‌های اضافه است. **هیچ Loss کوچکی گواه سود مالی، کالیبراسیون Quote و مناسب‌بودن برای معامله نیست**. برای ارتقا نیاز به ارزیابی آینده‌نگر مستقل و هزینه‌های واقعی داریم.

نکته: آرشیوهای قبلی را پاک نکنید و در صورت `SOURCE_AUDIT_FAILED` یا `INSUFFICIENT_GLOBAL_PURGED_GENUINE_SAMPLES` هیچ تقسیم زمانی یا داده‌ای را به‌صورت مصنوعی تکمیل نکنید.
