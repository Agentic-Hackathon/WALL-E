# مرز Shadow و LIVE

WallexLiveBroker موجود هیچ transport سفارش ندارد و پیش‌فرض HARD_DISABLED باقی ماند. داشتن کلید، پنج میلیون موجودی یا مشاهدهٔ package اجازهٔ ARM نیست. در این تحویل CLI روشن‌کردن LIVE عمداً وجود ندارد: هویت حساب مسابقه، credit غیرleveraged، بازار مجاز برگزارکننده، fee، tick/step/minimum، حقوق API، آزمون مثبت مالی و شواهد اقتصادی مستقل ناقص‌اند.

`atlas_live_readiness --private-read` فقط از WALLEX_API_KEY محیطی و GETهای allowlist استفاده می‌کند. فایل pass.txt یا .env خوانده نمی‌شود. redirect در درخواست خصوصی غیرفعال است. پاسخ خصوصی در atlas_store/operations/private_account_read.json محلی می‌ماند؛ گزارش انتشار فقط وضعیت را دارد. /sub-accounts، balances-detail و package مشخص از client موجود؛ fee طبق مستند رسمی /v1/account/fee. این endpointها به تنهایی همهٔ محدودیت‌های مسابقه را اثبات نمی‌کنند. منبع: https://developers.wallex.ir/basicservices/mainaccountwallet و https://api-docs.wallex.ir/ ؛ موجودی حساب اصلی از اعتبار اختصاصی جداست.

`atlas_order_protocol` تنها قرارداد metadata پایدار SQLite است: NEW→SUBMITTED→ACKNOWLEDGED→PARTIALLY_FILLED/FILLED/CANCELED/REJECTED/UNKNOWN. ID تکراری با تغییر نماد/سمت رد، سفارش متضادِ باز/UNKNOWN رد و UNKNOWN قابل retry خودکار نیست. hash status جای پاسخ معتبر API یا Fill مالی را نمی‌گیرد. تست status بدون قیمت/مقدار مالی، آزمون execution صرافی نیست. کنترل cross-account self-trade و reconciliation واقعی هنوز BLOCKED است.

Shadow از عمق واقعی، فرض fee و همان Gate مستقل استفاده می‌کند. افزودن به موقعیت مجاز نشده و تغییر Gate برای اجرای ADD انجام نشد. گزارش cash-only جای آزمون خرید/فروش مالی را نمی‌گیرد. تا وقتی این موارد حل نشده‌اند، نگه‌داشتن cash و عدم معامله نتیجهٔ ایمن مجاز است. UI و GitHub هیچ راه خودکاری برای ARM، ارسال سفارش یا نصب سرویس ندارند.
