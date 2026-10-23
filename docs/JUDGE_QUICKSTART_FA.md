# اجرای داور

دسترسی read-only ریپوی خصوصی را از مالک سازمان بگیرید؛ Token را در چت یا URL نگذارید. Git و Conda رسمی، Python 3.12 و محیط جدا لازم‌اند. مراحل دقیق نصب در نسخهٔ انگلیسی همین راهنماست. محیط `shbk` موجود را تغییر ندهید.

```powershell
conda run --no-capture-output -n shbk python scripts/judge_preflight.py
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
conda run --no-capture-output -n shbk python -m pytest -q
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_console --port 8766
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_cli data-sync-plan --top 2 --sync-hours 48
```

بدون داده/وزن واقعی preflight باید BLOCKED و UI باید DATA_NOT_AVAILABLE بدهد. این شکست سودآوری یا خطای مخفی نیست. دریافت عمومی تازه با data-sync-run، پس از مشاهدهٔ --help و plan، اختیاری است. Checkpoint تأییدشده باید با recipe و SHA از پژوهش داخلی تأمین شود؛ وزن ناشناس و دادهٔ ساختگی ممنوع است.

نتیجهٔ واقعی clean clone و نصب جدا در `reports/fresh_clone_test.json` ثبت می‌شود. اصل مطالعهٔ M8 تنها با سورس منجمد و تمام ورودی‌های محلی برابر قابل ادامه است؛ source جدید به‌صورت صادقانه نشست قبلی را رد می‌کند. برای گزارش تاریخی از UI فقط‌خواندنی استفاده کنید، نه اجرای مجدد پیش‌فرض آن نشست. مدل جدید خودکار promote نمی‌شود. توقف با Ctrl+C است؛ سرویس دائمی یا LIVE با این دستورها فعال نمی‌شود.
