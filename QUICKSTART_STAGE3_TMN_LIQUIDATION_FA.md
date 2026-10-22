# نصب مرحله سوم روی شاخه Stage 2

مرحله دوم در Git شما: `integration/atlas-broker`، commit آغازین `58d3236`.

1. هنگام اجرای حلقه `watch` منبع برنامه را تغییر ندهید؛ تا پایان یک چرخه با Ctrl+C متوقف کنید. Snapshotها، `watch_session.json` و `atlas_store` پاک نمی‌شوند.
2. فایل ZIP پچ Stage3 را در **ریشه** `D:/Hackaton/Wallex/wallex_agent_v3` Extract کنید. ZIP فقط اسکریپت نصب و patch متنی را دارد؛ به کد موجود دست نمی‌زند.
3. در Git Bash:

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage3_liquidation.sh
```

اسکریپت commit آغازین را کنترل می‌کند، شاخه `integration/atlas-tmn-liquidation` را می‌سازد، پچ را اعمال می‌کند، همه تست‌ها را اجرا می‌کند و سپس commit می‌سازد. در صورت شکست تست، commit ساخته نمی‌شود.

## مشاهده فقط‌خواندنی

```bash
python -m wallex_bot.atlas_cli liquidation-status
python -m wallex_bot.atlas_cli broker-status
```

`liquidation-status` هیچ سفارش و حتی فایل ledger جدیدی تولید نمی‌کند. داده‌های گزارش، Shadow هستند؛ موجودی واقعی حساب مسابقه را این دستور نمی‌خواند.

## بستن خودکار پایان Watch

پایان `watch --hours 48` با استفاده از دفتر سفارش واقعی تازه و ثبت سند SHA-256، یک درخواست `FINAL_TMN` برای هر موقعیت فرضی می‌سازد. اگر بهترین Bid مقدار کافی نداشته باشد، هیچ فروش فرضی ثبت نمی‌شود؛ وضعیت `CLOSED_WITH_UNRESOLVED_PAPER_POSITIONS` ذخیره می‌شود.

برای تلاش دوباره **پس از پایان زمان ثبت‌شده Watch**، در صورت باقی ماندن موقعیت‌ها:

```bash
python -m wallex_bot.atlas_cli liquidate-paper
```

این فرمان فقط موجودی فرضی را مدیریت می‌کند و هیچ API خصوصی یا ثبت سفارش زنده‌ای ندارد. `--fee` پیش‌فرض 0.001 یک **فرض پژوهشی** است؛ کارمزد واقعی تأییدنشده است. هیچ قیمتی با داده قبلی، آخرین کندل یا حدس جایگزین نمی‌شود.

## فایل‌های نتیجه

- `atlas_store/last_paper_liquidation_report.json`: هر تلاش، Quote SHA، دلیل رد، وضعیت موقعیت‌های باقی‌مانده.
- `atlas_store/liquidation_observations/*.json`: پاسخ خام و واقعی دفتر سفارش و زمان دریافت آن.
- `atlas_store/shadow.sqlite`: زنجیره هش تصمیم‌ها و Broker idempotency.

**تا زمان تأیید مجوزهای مسابقه و پیاده‌سازی و آزمایش مسیر واقعی سفارش، تسویه حساب مسابقه عمداً غیرممکن است.** از این خروجی نمی‌توان تحقق سود/زیان واقعی را استنتاج کرد.
