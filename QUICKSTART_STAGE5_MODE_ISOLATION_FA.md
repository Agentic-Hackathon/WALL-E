# راهنمای نصب مرحله ۵ — جداسازی BACKTEST، SHADOW و LIVE

## نصب امن
۱. اجرای `watch` را در پایان یک چرخه متوقف کنید تا کدِ درحال‌اجرا را در میانه فرآیند جایگزین نکنید.
۲. بسته ZIP پچ را در ریشه واقعی پروژه `/d/Hackaton/Wallex/wallex_agent_v3` استخراج کنید؛ پوشه `atlas_store` را پاک نکنید.
۳. اسکریپت را اجرا کنید؛ فقط روی commit `1e0654f` در شاخه `integration/atlas-validation` اعمال می‌شود.

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage5_mode.sh
```

## بررسی
```bash
python -m pytest -q
python -m wallex_bot.atlas_cli mode-status
python -m wallex_bot.atlas_cli validate --mode BACKTEST --resolution 15 --top 8
python -m wallex_bot.atlas_cli context-preview
```

برای ادامه Session قبلی (همه معاملات فرضی):
```bash
python -m wallex_bot.atlas_cli watch --mode SHADOW --hours 48
```

## ممنوعیت‌ها
- `watch --mode BACKTEST`، `agent-cycle --mode BACKTEST`، و `validate --mode SHADOW` رد می‌شوند.
- `--mode LIVE` در تمام فرمان‌ها رد می‌شود. نه API Key لازم است، نه امکان ارسال سفارش واقعی اضافه شده است.
- تست‌ها داده قیمت، کندل، خبر یا معامله فرضی نمی‌سازند. مطالعات آماری قبلی همچنان فقط گزارش پژوهش هستند.

## آنچه حل نشده
- خبر هنوز ورودی مستقیم Transformer نیست و اعتبارسنجی خارج نمونه اقتصادی Champion موجود نیست.
- استفاده از حافظه وزن‌دار FinMem، replay تصمیم و توضیح‌گر مشاوره‌ای LLM مربوط به گام‌های بعدی است.
