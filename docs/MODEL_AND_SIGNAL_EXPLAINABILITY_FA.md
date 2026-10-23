# مدل، سیگنال و توضیح

شرح اصلی از سورس و receipt در MODEL_CARD.md، ARCHITECTURE_FA.md، DECISION_TRACE.md و AGENTIC_ARCHITECTURE_FA.md است. Champion PatchTST، challengerهای M5 و baselineها با prediction_id/model SHA تفکیک می‌شوند؛ quantile بازده لگاریتمی احتمال تضمینی رشد نیست. Close-to-close با forward mid proxy یکی نیست.

۱۰ نقش قطعی، نه ۱۰ LLM، ابتدا واقعیت‌ها و هزینه را نقد می‌کنند. مدل q10 زیر هزینه می‌تواند پیش از ساخت توضیح ورود را رد کند؛ متن توضیح علت پس از اجرا اجازهٔ سفارش نمی‌سازد. Evidence IDs، زمان دسترسی، hash، allocation، intent و receipt در UI قابل مشاهده‌اند. حافظهٔ PIT یا خبر بدون مجوز/اعتبارسنجی حق ایجاد رأی معاملاتی ندارند. Missing خبر neutral نیست. نتیجهٔ منفی یا STAY_IN_CASH پنهان نمی‌شود.

آزمون‌های مرزی status/clock غیرمالی‌اند؛ فقط receipt واقعی و دفتر سفارش واقعی می‌توانند شواهد حسابداری باشند. Positive financial branches، partial/cancel صرافی و سود خارج از نمونه هنوز اثبات نشده‌اند. منابع/commits/مجوزها در THIRD_PARTY_ATTRIBUTION.md تفکیک direct/adapted/conceptual دارند.
