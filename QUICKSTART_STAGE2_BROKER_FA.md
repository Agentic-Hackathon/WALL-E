# راهنمای مرحله دوم Wallex Atlas — Broker abstraction (فقط Dry Run/Shadow)

## نصب روی پروژه محلی

مرحله اول باید روی branch `integration/atlas-risk-gate` با commit `95206c5` موجود باشد. بهتر است هنگام نصب `watch` در حال اجرا نباشد؛ `atlas_store` را حذف نکنید.

بسته PATCH حاوی `patches/atlas_stage2_broker.patch` و `scripts/apply_broker_stage2.sh` است. فایل‌ها را در ریشه `wallex_agent_v3` استخراج و سپس اجرا کنید:

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_broker_stage2.sh
```

اسکریپت فقط روی HEAD دقیق `95206c59c314720762c448c21cada5fd0e944de7` و با فایل‌های tracked تمیز کار می‌کند، شاخه `integration/atlas-broker` می‌سازد، Patch را با `git apply --check` بررسی و اعمال می‌کند، تمام تست‌ها را اجرا می‌کند و فقط در صورت موفقیت یک commit محلی می‌سازد. **هیچ سفارش واقعی ارسال نمی‌شود.**

پس از نصب:

```bash
python -m wallex_bot.atlas_cli broker-status
python -m wallex_bot.atlas_cli contest-readiness
```

برای ادامه Shadow از دستور فعلی `watch --hours 48` استفاده کنید. این پروژه خودِ `atlas_store` را پاک یا reset نمی‌کند. رکوردهای قبلی PaperAccount بدون شناسه idempotency باقی می‌مانند؛ حفاظت جدید برای درخواست‌های پس از نصب است.

## نکته مهم در مورد تست‌ها و محیط ویندوز

تست محلی این بسته با داده واقعی یا ساختگی بازار کار نمی‌کند؛ فقط قرارداد و حالت‌های رد سفارش بدون داشتن Quote واقعی را می‌سنجد. اجرای `pytest` در محیط این بسته نتیجه `60 passed, 5 skipped` داشته است. اگر ویندوز همان خطای ABI میان NumPy/SciPy/scikit-learn را نشان دهد، اسکریپت با وضعیت ناموفق متوقف می‌شود و کد را commit نمی‌کند؛ ترجیحاً محیط `shbk` را پیش از رفع ناسازگاری نسخه‌ها بی‌برنامه ارتقا ندهید.

## مرزهای قابلیت

- `ShadowBroker`: از `PaperAccount` فعلی استفاده می‌کند؛ fill فقط فرضی است و از قیمت ساختگی استفاده نمی‌کند.
- `WallexLiveBroker`: به‌رغم نامش، فقط یک **stub امن غیرقابل‌اجرا** است. با `live_enabled=True` قطعاً خطا می‌دهد؛ حتی با API Key معتبر نیز سفارش ثبت نمی‌کند.
- `reconcile()` در Live فقط سلامت و وضعیت ژورنال محلی را می‌سنجد؛ هنوز وضعیت سفارش صرافی را دریافت نمی‌کند. عبارت `submitted_exchange_orders=0` صرفاً به درخواست‌های ساخته‌شده **توسط این ماژول** اشاره دارد؛ اثبات نمی‌کند حساب در جای دیگری سفارش ندارد.
- `OrderState.UNKNOWN` مانع ارسال مجدد کورکورانه در توسعه آینده خواهد بود؛ idempotency واقعی صرافی و نحوه پیوند دادن شناسه‌های سفارش هنوز تأیید نشده‌اند.
- فعال‌سازی معامله واقعی، API مجاز بازارها، پکیج، کارمزد واقعی و تأیید تعلق کلید به حساب مسابقه را نیاز دارد و در این مرحله عمداً اضافه نشده است.
