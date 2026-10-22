# Stage 9 — راهنمای تشخیص عملیاتی

فایل‌های ZIP پچ را فقط در ریشه `wallex_agent_v3` استخراج و بعد اجرا کنید:

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage9_operations.sh
python -m wallex_bot.atlas_cli operations-report
```

این دستور تنها وضعیت پرونده‌های محلی را می‌خواند و برای اجرای هم‌زمان با Watch مناسب است؛ هیچ دانلود یا سفارش جدیدی انجام نمی‌دهد. خروجی `REJECTED` به کلاس استثنا محدود است تا متن آزاد خطا و اطلاعات حساس را منتشر نکند. مقدار `q10_above_observed_cost_threshold` صرفاً تحلیل هزینه بر مبنای Bid/Ask واقعی مشاهده‌شده و فرض کارمزد است، نه بازده تحقق‌یافته.

**برآورد اقتصادی Champion و تأیید کارمزد واقعی در این مرحله انجام نشده است.**
