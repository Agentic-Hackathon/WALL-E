# WALL-E — Wallex Atlas

نسخهٔ پژوهشی مسابقه، نه سامانهٔ دارای مجوز معاملهٔ واقعی. LIVE سخت غیرفعال است؛ هیچ مزیت اقتصادی مستقل اثبات نشده است. داده، مدل‌ها و نشست‌های قبلی روی دستگاه حفظ می‌شوند و وزن/اطلاعات حساب به GitHub نمی‌روند.

شروع داور: [راهنمای فارسی](docs/JUDGE_QUICKSTART_FA.md)، [انگلیسی](docs/JUDGE_QUICKSTART_EN.md)، [معماری](docs/ARCHITECTURE_FA.md)، [مدل و محدودیت](docs/MODEL_CARD.md)، [منابع](docs/THIRD_PARTY_ATTRIBUTION.md).

```powershell
conda run --no-capture-output -n shbk python scripts/judge_preflight.py
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_console --port 8766
```

UI در localhost فقط‌خواندنی است؛ دادهٔ مفقود را نمی‌سازد. اطلاعات واقعی، Shadow و snapshotهای تاریخی برچسب جدا دارند. اعتبار مسابقه با موجودی معمولی یا عدد پنج میلیون متن قوانین تأیید نمی‌شود. هیچ دکمهٔ روشن‌کردن LIVE نداریم.

موعد: ۲۳ اکتبر ۲۰۲۶ ساعت ۲۳:۵۰ ایران؛ توقف ورود از ۲۲:۵۰ و برنامهٔ خروج از ۲۳:۰۰. پس از موعد HALTED، حتی فروش باقی‌مانده خودکار نیست. فروش کامل تضمین نمی‌شود. [Runbook موعد](docs/TRADING_DEADLINE_1405_08_01_FA.md).

Clone تمیز فاقد archive و checkpointهاست. preflight صادقانه BLOCKED می‌دهد؛ برای مشاهدهٔ گزارش‌ها/UI مدل لازم نیست. تغییرات این تحویل، نسخهٔ منجمد M8 نیستند؛ نشست قبلی را با سورس جدید اجرا نکنید. manifest مستقل جدید فقط tracked source را می‌سنجد. [بازتولید](docs/REPRODUCIBILITY.md).
