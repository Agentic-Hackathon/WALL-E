# معماری Agentic — پروفایل پژوهشی Milestone 8

این پروفایل مسیر قدیمی Watch/LangGraph را حذف نمی‌کند. اجرای آن فقط با entry point جدید `wallex_bot.atlas_intelligence` و حساب پژوهشی مستقل `milestone8` مجاز است.

جریان واقعی:

```text
DataSync موجود + NewsStore دارای Lease/Cursor
                     ↓
Sampler مستقل Quote ← صف موعد Forecast و Ledger پایدار
                     ↓
پنج Forecast واقعی؛ فقط Champion فعلی دارای صلاحیت بررسی معامله
                     ↓
Technical / News / Pattern / Regime / Memory + وضعیت حساب
                     ↓
LangGraph: Specialists & Cross-review → Portfolio Manager
                     ↓
همان RiskGate قطعی → Dynamic Shadow Adapter → شواهد/حافظه
```

SqliteSaver وضعیت گراف را در `agentic_checkpoints.sqlite` نگه می‌دارد. دریافت Book برای تحلیل تکرار نمی‌شود؛ Agentها همان Receipt واقعی Sampler را می‌خوانند. خبر، ابزار شبکه، کلید، متن آزاد LLM یا Pattern امکان ارسال سفارش ندارند.

هفت نقش قبلی حفظ شده‌اند و Pattern Retrieval، Research Memory و Market Data آن‌ها را تکمیل می‌کنند. ده خروجی تخصصی به معنی ده مدل زبانی نیست. مدل‌های پیش‌بینی واقعاً inference انجام می‌دهند؛ تحلیل‌گران ساختاریافتهٔ فعلی قطعی و شواهدمحورند. LLM تزئینی یا متن پس از تصمیم، شاهد ارزش افزوده AI معرفی نمی‌شود.

هر نقش شامل نام، زمان، نماد، Evidence ID، Source Hash، Signal، Confidence، Uncertainty، Limitations، Recommendation و Reasoning Summary است. Confidence بدون Calibration معتبر null باقی می‌ماند. پیام‌های Cross-review صلاحیت شواهد و اختلاف Technical/Forecast را ثبت می‌کنند. q10 واقعی مدل با هزینه مشاهده‌شده مقایسه و اثر آن **پیش از توضیح نهایی** در نقد ثبت می‌شود.

Pattern فاقد اعتبارسنجی مستقل، حافظه فاقد مطالعه ارزش افزوده و FinBERT فاقد مجوز مناسب مسابقه حق تبدیل‌شدن به رأی عددی سفارش را ندارند. نبود خبر، رأی خنثی جعلی نیست. خروجی مدل نیز هرگز نمی‌تواند Gate را دور بزند.

بازوهای از پیش تعریف‌شده شامل Rule-only، Forecast-only، Forecast+Technical/News/Pattern/Memory، Full و حذف Review/News/Pattern/Memory هستند. مقایسه برابری snapshot یا تغییر دلیل، معادل اثبات سود سیستم چندعاملی نیست؛ گزارش اقتصادی مستقل و داده مشترک کافی لازم است.

حافظه فقط افزایشی و PIT-safe است. ثبت و retrieval زمان مشاهده، availability و ایجاد واقعی را جدا کنترل می‌کند. نتیجه فرضی، سود واقعی نامیده نمی‌شود. Replay گرافِ ثبت‌شده، Gate و حسابداری را بدون سفارش یا ثبت حافظه جدید بررسی می‌کند. هیچ Promotion خودکار یا تغییر وزن مدل وجود ندارد.
