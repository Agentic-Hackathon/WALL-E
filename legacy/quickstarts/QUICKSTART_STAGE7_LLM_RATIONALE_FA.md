# نصب و استفاده Stage 7 — LLM Rationale (مشاوره‌ای)

## نصب روی شاخه موجود

پچ ZIP را داخل ریشه `wallex_agent_v3` استخراج کنید. آرشیو `atlas_store`، Checkpointها و فایل‌های نشست Watch را **حذف یا جایگزین نکنید**. برای نصب، `watch` را در پایان یک چرخه متوقف کنید:

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage7_rationale.sh
```

اسکریپت فقط روی `integration/atlas-finmem-memory` با commit `ddc22e0` عمل می‌کند، شاخه جدید `integration/atlas-llm-rationale` را می‌سازد، تست می‌گیرد، سپس commit ثبت می‌کند.

## اجرا بدون Ollama

```bash
python -m wallex_bot.atlas_cli rationale-status
python -m wallex_bot.atlas_cli agent-cycle --mode SHADOW --symbol BTCTMN
```

`agent-cycle` هنوز به کندل تازه واقعی، Checkpoint تأییدشده و Order Book واقعی والکس نیاز دارد. اگر Ollama در رایانه نصب و فعال نباشد، گره توضیح‌گر `LOCAL_LLM_UNAVAILABLE` را گزارش می‌کند؛ **نه** متن ساختگی. اجرای Shadow طبق کد موجود مستقل از متن توضیح انجام می‌شود و ممکن است بنا بر RiskGate هیچ معامله فرضی نکند.

## مدل زبانی محلی اختیاری

در حالت پیش‌فرض، سیستم فقط در `127.0.0.1:11434` دنبال Ollama می‌گردد. اگر مدل چت محلی نصب باشد، مدل محلی را خودکار شناسایی می‌کند. در صورت نیاز می‌توان پیش از اجرای `agent-cycle` متغیر `ATLAS_LLM_MODEL` را به نام دقیق **مدل محلی از قبل نصب‌شده** تنظیم کرد؛ به هیچ کلید سرویس ابری نیازی نیست. برای خاموش‌کردن کامل: `export ATLAS_LLM_PROVIDER=disabled`. این متغیرها اختیاری‌اند و هرگز مجوز معامله صادر نمی‌کنند.

برای مشاهده وضعیت کش بدون ایجاد دیتابیس یا شبکه:

```bash
python -m wallex_bot.atlas_cli rationale-status
```

برای ادامه Watch قبلی (Watch فعلی به LangGraph و LLM متصل نیست):

```bash
python -m wallex_bot.atlas_cli watch --mode SHADOW --hours 48
```

## محدودیت‌ها

- خروجی مدل زبانی **توضیح غیرمعتبرسنجی‌شده** است؛ ممکن است اشتباه کند و به هیچ عنوان تصمیم معاملاتی، veto، وزن مدل یا RiskGate را عوض نمی‌کند.
- تنها یک گره به `agent-cycle` اضافه شده؛ حلقه Watch هنوز جریان مستقل Shadow را اجرا می‌کند.
- متن خبر، URLs، کلیدها و محتوای آزاد حافظه به LLM داده نمی‌شود. تنها تعداد خبرهای مشاهده‌شده و کد veto ساختاریافته ممکن است ارائه شود. بنابراین **تحلیل محتوایی خبر توسط LLM اینجا انجام نمی‌شود**.
- هش prompt و پاسخ LLM واقعی ذخیره می‌شوند. این کش خروجی دقیق را حفظ می‌کند اما نمی‌تواند به‌تنهایی نسخه داخلی وزن‌های مدل Ollama را اثبات کند؛ برای بازپخش کامل، نسخه آن مدل نیز باید فریز شود.
- هیچ API ثبت سفارش واقعی، بازده تحقق‌یافته، یا سود خارج از نمونه در این مرحله اثبات نشده است.
