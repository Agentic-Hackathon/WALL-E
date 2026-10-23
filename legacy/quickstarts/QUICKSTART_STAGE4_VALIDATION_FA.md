# راهنمای Stage 4

1. پس از حفظ نسخه فعلی و توقف Watch فقط در صورت تغییر سورس درحین اجرا، ZIP پچ را در **ریشه** `wallex_agent_v3` استخراج کنید (پوشه `atlas_store/` را حذف نکنید).
2. محیط Git Bash و `shbk`:

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage4_validation.sh
```

این اسکریپت **فقط** روی `integration/atlas-tmn-liquidation` در commit `1f43a04` و working tree تمیز کار می‌کند؛ شاخه `integration/atlas-validation` می‌سازد؛ پس از موفقیت تست‌ها commit می‌زند.

3. ارزیابی بدون سفارش، بدون دانلود جدید و بدون تغییر مدل:

```bash
python -m wallex_bot.atlas_cli validate --resolution 15 --top 8
```

خروجی: `atlas_store/reports/stage4_validation.json`. پیش از خواندن عدد، `fee_verified_with_exchange: false` و `status` را ببینید. اگر آرشیو واقعی معتبر کم است، باید `INSUFFICIENT_EVIDENCE` ببینید؛ از این گزارش هیچ ادعای سود واقعی استخراج نکنید.

4. بررسی پایانی Stage3:

```bash
python -m wallex_bot.atlas_cli liquidation-status
python -m wallex_bot.atlas_cli liquidate-paper
```

اگر سبد کاغذی خالی و watch session وجود داشته باشد، فرمان دوم `ALREADY_FLAT` برمی‌گرداند، نه یک خرید یا فروش. اگر موقعیتی باز باشد، قبل از پایان زمان همچنان با `BrokerSafetyError` متوقف می‌شود. وضعیت ثبت‌شده `RUNNING` در watch به‌تنهایی گواه فعال بودن یک process نیست.

**هیچ مدلی از طریق این ابزار promote نمی‌شود؛ Live همچنان خاموش است.**
