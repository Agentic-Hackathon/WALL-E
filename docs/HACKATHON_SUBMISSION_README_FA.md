# تحویل پژوهشی Wallex Atlas — Milestone 8

این نسخه، ادغام عملیِ بازیابی الگو، مرور چندعاملی، همگام‌سازی خبر و مدیریت محافظه‌کارانهٔ Shadow است؛ مجوز معاملهٔ واقعی یا اثبات سودآوری نیست. Champion، دو Transformer و RiskGate جایگزین نشده‌اند. LIVE همچنان HARD_DISABLED است.

## اجرا در محیط موجود

از ریشهٔ پروژه، با محیط فعلی `shbk` اجرا کنید. محیط مشترک را با نصب مجدد بسته‌ها تغییر ندهید؛ `requirements-m8.txt` ثبت نسخه‌های مشاهده‌شده برای ساخت محیط جداست، نه ادعای نصب آزمایش‌شده از صفر. آرشیو واقعی، کاتالوگ و Checkpointهای دارای هش لازم‌اند؛ داده و وزن ساختگی همراه تحویل نیست.

```powershell
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_intelligence status
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_intelligence sync-status
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_intelligence run
```

فرمان آخر foreground است؛ بستن آن به معنی توقف جمع‌آوری است. اجرای دوباره همان قرارداد و پیشرفت را ادامه می‌دهد، ولی شکاف آفلاین به مشاهدهٔ تاریخی تبدیل نمی‌شود. برای اجرای محدود، `--max-runtime-seconds 130` اضافه کنید. دو نمونه به کمک lease مشترک از تصاحب هم‌زمان نشست منع می‌شوند. کد/وزن/محیط را هنگام نشست تغییر ندهید؛ تغییر، نشست جدید می‌خواهد.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
conda run --no-capture-output -n shbk python -m pytest -q --junitxml=reports/m8_pytest.xml
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_intelligence replay
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m8_evaluation
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m8_report
```

مقادیر واقعی آخرین اجرای محدود در `reports/m8_shadow_results.json` و گزارش فارسی مرحله ثبت می‌شوند. ۴۸ ساعت صرفاً مدت قرارداد است، نه مدت سپری‌شده یا uptime اثبات‌شده.

## محدودیت‌های مهم

- ده نقش ساختاریافته و چهار گره واقعی LangGraph داریم، نه ده فراخوانی LLM. پیش‌بینی عددی Champion پیش از توضیح، تحت کنترل ریسک بررسی می‌شود.
- Pattern و حافظه در شواهد حضور دارند، ولی افزایش بازده مستقل ثابت نشده و اجازهٔ ایجاد سفارش نمی‌دهند.
- FinBERT ذخیره‌شده مجوز NC دارد؛ در مسیر مسابقه اجرا/رأی‌دهی نمی‌کند. چهار بازوی دادهٔ خبر وجود دارند، ولی دادهٔ مشترک تاریخی PIT کافی نیست.
- ADD با RiskGate فعلی مجاز نیست. REBALANCE تراکنش اتمیک ساختگی ندارد؛ خروج و ورود جداگانه باید دوباره مجاز شوند.
- نبود ورود مجاز واقعی/موقعیت نگهداری‌شده، اعتبارسنجی مالی BUY/SELL/REDUCE را محدود می‌کند. خروجی عمق دفتر، fill صرافی نیست.
- کارمزد .001 در هر سمت فقط فرض قرارداد است. اعتبار حساب مسابقه، فهرست مجاز برگزارکننده و کارمزد واقعی تأیید نشده‌اند.
- گزارش بازآزمایی، replay شواهد واقعی ثبت‌شده است؛ بک‌تست اقتصادی مستقلِ بلندمدت و ablation سودآوری را اثبات نمی‌کند.

راهنمای معماری، روش الگو، سیاست پرتفوی و توضیح تصمیم در همین پوشه‌اند. manifest تحویل فقط هش وزن‌ها را دارد. هیچ انتشار GitHub، ارسال مسابقه یا ضبط ویدئو از سوی این اجرا انجام نشده است.
