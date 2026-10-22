# اجرای V3.2 روی آرشیو قبلی

**روش پیشنهادی:** پچ V3.2 را مستقیم داخل `D:/Hackaton/Wallex/wallex_agent_v3` استخراج کنید و فایل‌های هم‌نام را جایگزین نمایید؛ `atlas_store` را دست‌نخورده نگه دارید.

در Git Bash با محیط `shbk` و از پوشه فوق کافی است یک فرمان بدون پارامتر اجرا شود:

```bash
bash run_v3_2.sh
```

یا برای اجرای مرحله‌به‌مرحله:

```bash
python -m pytest -q
python -m wallex_bot.atlas_cli audit-v3
python -m wallex_bot.atlas_cli train-deep
python -m wallex_bot.atlas_cli audit-v3
python -m wallex_bot.atlas_cli shadow-cycle
```

هیچ متن جایگزین‌شدنی، نام دارایی، Package ID یا فایل قابل‌پرکردن در دستورات بالا وجود ندارد. خروجی audit در `atlas_store/reports/v3_2_audit.json` ثبت می‌شود. اگر نسبت آموزش/اعتبارسنجی قابل‌قبول نباشد، آموزش اجرا نمی‌شود و صریحاً دلیل را اعلام می‌کند. هیچ داده مصنوعی برای رفع کمبود داده تولید نمی‌شود.

برای اجرای یک چرخه کامل پژوهش کوتاه‌مدت همراه با به‌روزرسانی آرشیو واقعی در ۲۰ بازار منتخب:

```bash
python -m wallex_bot.atlas_cli run --days 3 --limit-markets 20
```

این فرمان ممکن است دوباره به API عمومی والکس درخواست بزند؛ بخش‌های کش‌شده مجدداً دریافت نمی‌شوند. **هیچ فرمانی در این نسخه معامله واقعی یا برداشت انجام نمی‌دهد.**
