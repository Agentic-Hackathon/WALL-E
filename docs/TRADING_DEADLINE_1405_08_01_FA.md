# سابقهٔ موعد — ۱ آبان ۱۴۰۵

**به‌روزرسانی اپراتور:** موعد فعال اکنون یکشنبه **۳ آبان ۱۴۰۵ / ۲۵ اکتبر ۲۰۲۶ ساعت ۲۳:۵۰ تهران** است؛ توقف ورود ۲۲:۵۰ و آغاز خروج ۲۳:۰۰ همان روز. [راهنمای نسخهٔ جاری](CURRENT_RELEASE_FA.md) مرجع فعال است. متن پایین، سابقهٔ تحویل با موعد قبلی است؛ نشست‌ها، رسیدها و HALTED latchهای قبلی بازنویسی یا پاک نشده‌اند. این تمدید مجوز معامله یا تضمین تسویه ایجاد نمی‌کند.

موعد کاربر: جمعه ۲۳ اکتبر ۲۰۲۶ ساعت ۲۳:۵۰ Asia/Tehran = ۲۰:۲۰ UTC = ۲۲:۲۰ Europe/Berlin. از zoneinfo و ساعت timezone-aware استفاده می‌شود؛ تغییر DST برلین در روزهای بعد، ساعت ایران را عوض نمی‌کند. تاریخ Sessionهای قبلی و ساعت M8 دست نمی‌خورد.

سیاست مستقل `atlas_deadline`: قبل از ۲۲:۵۰ collecting؛ از ۲۲:۵۰ entry_disabled؛ از ۲۳:۰۰ exit_only؛ در ۲۳:۵۰ HALTED. در مرز خرید جدید BUY/ADD/REBALANCE رد می‌شود؛ بعد از halt هیچ خرید/فروش/لغو خودکار مجاز نیست. ساعت کندل یا ساعت ساختگی برای تغییر phase استفاده نمی‌شود.

شرط ساعت: HTTP Date از GET عمومی HTTPS والکس، RTT <=۴ثانیه، cache Age<=۱ثانیه، اختلاف حداکثر۵ثانیه و receipt تازه. برای جلوگیری از خروج پس از deadline با ساعت محلی عقب‌تر، gate از ساعت دیرترِ محلی/سرور به‌علاوهٔ عدم قطعیت استفاده می‌کند. نبود/خرابی/کهنگی ساعت fail-closed است. HTTP Date می‌تواند ساعت واسطه باشد؛ تأیید حقوق معاملاتی نیست.

```powershell
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_deadline status
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_deadline clock-check
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_deadline watchdog --root atlas_store
```

watchdog یک فرآیند foreground مستقل از GUI است و به‌صورت خودکار نصب/راه‌اندازی مجدد نمی‌شود؛ اپراتور باید آگاهانه آن را روشن و پایش کند. برای حساب پژوهشی جدا، --root همان پوشهٔ حساب/Session باشد؛ receipt ساعت مشترکِ بدون تصریح به آن کپی نمی‌شود. هنگام توقف، مجوز باقی‌ماندهٔ watchdog باطل می‌شود. crash موجب کهنگی و fail-closed می‌شود. سرویس Windows Task Scheduler نصب نشده است؛ راه‌اندازی آن فقط بعد از انتخاب صریح اپراتور و آزمون مانیتورینگ مجاز است.

این gate به مرز M8 DynamicShadow جدید اضافه شده است، نه به RiskGate یا کد منجمد قدیمی. PaperAccount/Broker/Agent قدیمی برای سازگاری و replay تاریخی تغییر نکرده‌اند؛ مسیر قدیمی را برای عملیات مسابقه استفاده نکنید. هیچ مسیر LIVE در پروژه قادر به ارسال سفارش نیست. این نسخه سرویس unwind واقعی یا لغو سفارش صرافی را پیاده/فعال نمی‌کند، زیرا حساب/مجوز/transport تأیید نشده و مثبت‌های مالی Shadow هم اثبات نشده‌اند. وضعیت آن صریحاً BLOCKED است.

Runbook اپراتور: پیش از entry-stop، حساب اختصاصی/credit/fee/market permissions و تمام سفارش‌های باز را از منبع معتبر read-only بررسی کنید. در exit-only فقط زیر مجوز مستقل Gate، client ID و کنترل self-trade، خروج مجاز بررسی شود؛ UNKNOWN پیش از retry باید reconcile شود. Timeout دلیل قطعی reject نیست. بعد از موعد، برای residual حتی فروش خودکار نکنید؛ گزارش فوری `UNLIQUIDATED_RESIDUAL_MANUAL_REVIEW` و اقدام انسانی با مجوز جدید لازم است. موجودی نامعلوم را صفر یا تسویه‌شده ننامید. هیچ تضمین فروش کامل وجود ندارد.
