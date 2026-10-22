# راهنمای Stage 11 — ممیزی سلامت ویژگی‌ها

۱. اگر Watch فعال است، در مرز یک چرخه متوقف کنید. **هیچ چیزی از atlas_store حذف نکنید.**
۲. فقط ZIP پچ Stage 11 را در ریشه Git پروژه استخراج کنید؛ تنها اسکریپت نصب و Patch از قبل کپی می‌شوند.
۳. دستورات Git Bash:

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage11_feature_health.sh
```

اسکریپت فقط از `integration/atlas-edge-triage` در `cec0a32` شروع می‌کند و پس از `118 passed, 5 skipped` شاخه `integration/atlas-feature-health` را commit می‌کند. اگر وضعیت repo با این فرض منطبق نبود، متوقف می‌شود.

## اجرا

```bash
python -m wallex_bot.atlas_cli feature-health --resolution 15 --top 8
python -m wallex_bot.atlas_cli feature-health --resolution 15 --symbol BTCTMN
```

فیلدهای مهم: `invalid_columns_latest`، `invalid_counts_in_context_window`، `recorded_denominator_conditions`، `observed_contiguous_bars`، `minutes_quote_after_last_closed_candle`، `can_use_unchanged_champion`. انتخاب ۸ نماد بر اساس حجم معامله ثبت‌شده در Catalog است، نه انتخاب بازده.

اگر `MODEL_INPUT_WINDOW_FINITE` مشاهده شد، **تنها** سلامت ۱۶ ستون موجود و کفایت تاریخچه در آن Snapshot بررسی شده است؛ نه این‌که پیش‌بینی دقیق، سودآور یا قابل معامله شده باشد. اگر Snapshot قدیمی ردشدن را نتوان دوباره ساخت، خطای قدیمی را به‌عنوان اصلاح‌شده نخوانید.

**هیچ‌کدام از q50 و q90 به RiskGate متصل نشده‌اند.** معاملات واقعی غیرفعال‌اند.
