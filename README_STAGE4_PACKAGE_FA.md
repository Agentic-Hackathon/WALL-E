# Wallex Atlas Stage 4 — Git patch

این ZIP فقط دو فایل در ریشه پروژه اضافه می‌کند:
- `scripts/apply_stage4_validation.sh`
- `patches/atlas_stage4_validation.patch`

پس از استخراج داخل `wallex_agent_v3` (نه داخل پوشه زیرمجموعه جدید):

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage4_validation.sh
python -m wallex_bot.atlas_cli validate --resolution 15 --top 8
```

**پیش‌شرط سخت:** شاخه `integration/atlas-tmn-liquidation` در commit `1f43a04`؛ Git working tree tracked باید تمیز باشد. اسکریپت شاخه `integration/atlas-validation` می‌سازد، پچ را اعمال می‌کند، `pytest -q` را اجرا می‌کند و فقط پس از موفقیت commit ثبت می‌کند.

آرشیو واقعی، database، حساب، مدل Champion، WATCH session و keys را لمس نمی‌کند.

**توجه:** دستور `liquidate-paper` روی سبد کاغذی از پیش خالی اکنون `ALREADY_FLAT` می‌دهد، اگر Watch session وجود داشته باشد؛ اما برای هر موقعیت باز تا رسیدن به مهلت معتبر، Gate همان خطا را اعمال می‌کند. بدون وجود Watch session نیز fail-closed باقی می‌ماند.

جزئیات پس از نصب: `QUICKSTART_STAGE4_VALIDATION_FA.md`، `CHANGELOG_STAGE4_VALIDATION_FA.md`.
