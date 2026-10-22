# Stage 7 — توضیح‌گر LLM صرفاً مشاوره‌ای

- منبع مفهومی: TradingAgents از Tauric Research، commit `e8f5503e9b86d5c2710b0c76b1f686703968c9df`، مجوز Apache-2.0 طبق `third_party/SOURCES.md`. هیچ کد خارجی کپی نشده؛ این لایه مستقلاً نوشته شده است.
- افزودن `wallex_bot/atlas_rationale.py` با استخراج **فقط داده ساختاریافته مشاهده‌شده**، بدون متن خبر، لینک خبر، کلید API، قیمت ساختگی یا مسیر ارسال سفارش.
- افزودن گره `llm_rationale_agent` دقیقاً بعد از `risk_agent` و پیش از `shadow_execution_agent`. تنها خروجی گره `advisory_rationale` است؛ ورودی‌های تصمیم `ShadowBroker` و `RiskGate` دست‌نخورده مانده‌اند.
- تنها ارائه‌دهنده اختیاری `Ollama` لوکال روی `127.0.0.1:11434` است؛ نه ابزار LLM، نه endpoint خارجی و نه انتقال `WALLEX_API_KEY`. در نبود Ollama توضیح ساختگی ایجاد نمی‌شود و وضعیت `LOCAL_LLM_UNAVAILABLE` ثبت می‌گردد.
- خروجی‌های **واقعی** Ollama در `atlas_store/rationale_cache.sqlite` تحت هش SHA-256 ورودی ساخت‌یافته، نسخه Prompt و مدل درخواست‌شده به‌شکل immutable ذخیره می‌شوند. پاسخ کش‌شده فقط برای توضیح قابل مصرف است و اجازه ارسال یا تغییر سفارش ندارد.
- خروجی متن و وضعیت Advisory در رویداد قبلی `MULTI_AGENT_EXPLANATION` دفتر Shadow ثبت می‌شود؛ ثبت پیوسته فقط در `agent-cycle` انجام می‌شود، **نه** در حلقه مستقل `watch`.
- فرمان فقط‌خواندنی جدید: `python -m wallex_bot.atlas_cli rationale-status`.
- هیچ تغییری در `atlas_risk.py`، `atlas_broker.py`، `atlas_shadow.py`، مسیر `watch`، مدل‌های Transformer، `atlas_store`، اجازه LIVE یا کارمزد انجام نشده است.
- تست‌ها فقط قراردادهای ایمنی را بدون هیچ قیمت/کندل/خبر/نتیجه بازار ساختگی بررسی می‌کنند؛ سود یا بهبود پیش‌بینی اثبات نشده است.
