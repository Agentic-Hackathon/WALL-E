# نصب Stage 10 — بدون اینترنت و بدون سفارش

پایه: `integration/atlas-operational-audit` با HEAD `0bc8af2`. اجرای Watch را در مرز یک چرخه متوقف کنید؛ به دیتابیس‌ها و مدل‌ها دست نزنید.

ZIP پچ را در **ریشه** `wallex_agent_v3` استخراج کنید. بسته تنها Patch، اسکریپت نصب و README اولیه را دارد؛ فایل‌های Python و مستندات جدید فقط با Git Patch ایجاد می‌شوند تا خطای `already exists` رخ ندهد.

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage10_triage.sh
```

پس از نصب:

```bash
python -m wallex_bot.atlas_cli edge-triage
python -m wallex_bot.atlas_cli forward-report
python -m wallex_bot.atlas_cli mode-status
```

برای بررسی هویت نسخه:

```bash
git log -1 --oneline
python -m pytest -q
```

از خروجی `edge-triage` این فیلدها برای تصمیم توسعه بعدی مهم‌اند: `classified_rejections`، `q10_minus_cost_log_bps`، `q50_exceeds_assumed_cost_count_diagnostic_only`، `quote_received_after_feature_timestamp_minutes` و `future_quote_arrives_after_due_minutes`. تمام مقادیر مربوط به تاریخچه واقعی موجود است؛ هیچ مشاهده‌ای ساخته نمی‌شود.

وجود `q50_exceeds` مثبت به معنی مجوز خرید نیست. آستانه q10 و محافظت‌های ریسک همچنان باید پابرجا بمانند تا تحلیل قوی‌تری خارج از نمونه و با کارمزد تأییدشده انجام شود.
