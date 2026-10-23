# راه‌اندازی Stage 8: بازپخش فقط‌خواندنی RiskGate

1. اگر `watch` فعال است، آن را در مرز یک چرخه متوقف کنید. فایل ZIP پچ را در **ریشه** `wallex_agent_v3` استخراج کنید. برخلاف Stage 7، این بسته فایل‌های راهنما و سورسِ درون Git Patch را از قبل استخراج نمی‌کند؛ بنابراین نباید با `already exists` برخورد کنید.
2. روی `integration/atlas-llm-rationale`، commit `0b917d9` باشید. سپس:

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage8_replay.sh
```

3. بدون نیاز به API key، Ollama یا شبکه، رویداد جدیدتر را بررسی کنید:

```bash
python -m wallex_bot.atlas_cli replay-decision
python -m wallex_bot.atlas_cli replay-decision --event-id 1
```

برای تصمیم‌های ثبت‌شده **پیش از نصب Stage 8**، `LEGACY_NO_RISK_SNAPSHOT` انتظار می‌رود. **تنها تصمیم‌های جدید** که واقعاً توسط Watch/Agent با داده واقعی ثبت می‌شوند قابل بازپخش خواهند بود.

4. همان Session قبلی را با فرمان قبلی از سر بگیرید (اطلاعات Session پاک نمی‌شوند):

```bash
python -m wallex_bot.atlas_cli watch --mode SHADOW --hours 48
```

5. بعد از ایجاد یک تصمیم جدید (حتی HOLD/REJECTED به علت نبود داده واقعی)، دستور بازپخش را اجرا کنید. اگر آخرین رویداد جدید از نوع خطای عمومی خارج از Broker باشد، احتمالاً `LEGACY_NO_RISK_SNAPSHOT` می‌بینید؛ از روی گزارش رویدادهای Shadow، شناسه یک رویداد Broker را با `--event-id` مشخص کنید.

## وضعیت‌های خروجی

- `MATCH`: تصمیم *RiskGate* با ورودی و سورسِ ثبت‌شده دوباره همان نتیجه را داده است؛ **سود یا اجرای واقعی نیست**.
- `LEGACY_NO_RISK_SNAPSHOT`: داده کافی از قبل ثبت نشده است.
- `AUDIT_HASH_CHAIN_INVALID`/`SNAPSHOT_HASH_MISMATCH`: عدم تطابق تمامیت، بازپخش رد می‌شود.
- `RISK_CODE_VERSION_MISMATCH`/`RISK_POLICY_VERSION_MISMATCH`: نسخه RiskGate یکسان نیست؛ رد.
- `DECISION_DIVERGENCE`: اختلاف واقعی در نتیجه RiskGate و رویداد ثبت‌شده؛ بررسی اجباری، معامله جدید از این فرمان صادر نمی‌شود.
- `NO_EXISTING_SHADOW_LEDGER`: دفتر Shadow وجود ندارد.

فرمان‌ها هیچ سفارش واقعی نمی‌فرستند. هر تصمیم واقعی مسابقه نیازمند مجوزهای مستقل و زیرساخت اجرای زنده‌ای است که هنوز فعال نشده است.
