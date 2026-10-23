# گزارش تحویل WALL-E / Wallex Atlas

## نتیجهٔ واقعی

انتشار خصوصی با تاریخچهٔ Git، مستندات دوزبانه، نصب جدا، UI واقعی و کنترل موعد پیاده و آزمایش شدند. **سامانه برای LIVE آماده یا مجاز اعلام نشده است.** هیچ سفارش/برداشت/لغو واقعی، معامله، Fill یا تسویهٔ واقعی در این مأموریت انجام نشد. سود خارج از نمونهٔ تأییدشده نداریم.

مخزن: https://github.com/Agentic-Hackathon/WALL-E — private=true و مجوز push از API احرازشدهٔ GitHub با credential محلی تأیید شد. `gh` نصب نبود؛ آن را موفق اعلام نکردیم. اتصال GitHub داخلی برنامه 404 داد، ولی Git Credential Manager و API رسمی میزبان کار کردند. هیچ Token به چت/گزارش منتقل نشد.

مبنا دقیقاً `2fdaa10dc16fd5950036fdac422f106d10a3eeca` و شاخهٔ آغازین integration/atlas-milestone-8-agentic-patterns بود. شاخهٔ کار جدید `codex/publish-judge-live-ui` است. مخزن مقصد خالی بود و تاریخچه به main، بدون force/rewrite، فرستاده شد. تغییرات کد نهایی در `7aafed67102e5bfbbd4c6de6bcdf8f3679ad3d9a` ثبت و hash آن با remote تطبیق داده شد. commitهای گزارش پس از این نسخه می‌آیند؛ HEAD/tag نهایی تحویل را با گزارش ممیزی و دستور git ls-remote کنترل کنید.

Tag اجرایی تاریخی `atlas-m8-execution-a112709` دقیقاً به `a1127091d31702474c005af7f08aaf966321ced9` اشاره می‌کند. Tag تحویل `wall-e-submission-20261023` مجزاست و برابر نسخهٔ معاملاتی منجمد فرض نمی‌شود. نسخهٔ جدید نباید نشست M8 قدیمی را اجرا کند. برای داور، مالک سازمان باید کاربر مشخص داور را با نقش Read به همین مخزن خصوصی دعوت کند؛ دعوت یا عمومی‌کردن در این اجرا انجام نشد.

## امنیت انتشار و حفاظت

Gitleaks8.30.1 رسمی با checksum آرشیو رسمی کنترل و به‌صورت portable در .tools/ اجرا شد؛ binary در Git نیست. تمام commitهای reachable از HEAD قبل از Push اسکن شدند. هشدارهای اولیه به source SHA فایل wallex_api.py و هش دو فایل tokenizer پین‌شده مربوط بودند؛ هر مقدار با بایت فایل مرجع برابر شد. فقط fingerprint تاریخی دقیق در .gitleaksignore ثبت شد، نه غیرفعال‌کردن generic-key یا استثنای کل فایل. Secret واقعی تأییدشده یافت نشد؛ چرخش کلید به‌عنوان اقدام انجام‌شده ادعا نمی‌شود.

نام‌های حساس و مدل/DB در تاریخچه نیز ممیزی شدند؛ forbidden historical paths خالی بود. .gitignore برای pass.txt/.env*/DB/وزن/کش/لاگ/محیط/ZIP تکمیل شد. ignore جای ممیزی tracked/history را نگرفت. داده‌ها، Checkpointها، Sessionهای M7/M8، فایل‌های untracked و ZIPهای کاربر روی میزبان حفظ شدند. هشت Checkpoint، active_champion و قرارداد M7 با هش آغازین برابرند؛ گزارش `preserved_assets_audit.json` این را ثبت می‌کند. RiskGate، Broker، PaperAccount، Agent، دو Transformer و signals هسته‌ای نسبت به مبنا diff ندارند. فقط آداپتور opt-in جدید و لایه‌های خواندن/ایمنی توسعه یافتند.

manifest مستقل `scripts/judge_preflight.py` تنها فایل‌های tracked منتخبِ سورس/اسکریپت/وابستگی را می‌سنجد. ۱۱۳ ورودی آن در میزبان و Clone برابر شدند. دو helper محلی قدیمی خودکار commit نشدند؛ قرارداد اصلی M8 نیز اصلاح نشد. اصل «اجرای تاریخی با ورودی‌های همان دستگاه» از «پژوهش جدید روی Clone با دادهٔ عمومی تازه» جداست.

## نصب و تست واقعی

Clone واقعی از remote در .judge-clone انجام شد، نه فقط کپی فایل یا git archive. venv کاملاً جدا و بدون system-site-packages ساخته شد؛ نصب requirements-m8.txt واقعاً موفق بود و pip check خطا نداشت. نسخهٔ ۸۹ بستهٔ نصب‌شده در requirements-judge-lock.txt ثبت شد و تطبیق آفلاین آن با محیط نصب‌شده هم موفق بود. Python3.12/Windows x64 و torch2.11.0+cpu، CUDA=None/GPU=False مشاهده شد. محیط shbk/GPU میزبان تغییر نکرد.

- میزبان با دادهٔ اصلی: **319 passed, 5 skipped**؛ JUnit نهایی ۴۶٫۶۶ ثانیهٔ نمایش‌داده‌شده دارد. پنج skip همان ادغام‌های اختیاری قدیمی وابسته به ورودی/مجوز صریح‌اند.
- Clone بدون داده/وزن: **217 passed, 107 skipped، صفر failure/error**. preflight به‌درستی BLOCKED/DATA_NOT_AVAILABLE برای chunks و Champion می‌دهد. این نتیجه بازتولید مالی کامل نیست.
- اجرای اولیهٔ Clone: 196passed/42skip/6fail/59error؛ اجرای دوم 216passed/97skip/10error. علت: fixtureهای قدیمی فرض می‌کردند فایل یا جدول واقعی حاضر است؛ بعضی تست‌ها schema خالی ایجاد کرده و اجرای بعدی را گمراه می‌کردند. guard نبود resource/table اضافه شد؛ assertionهای واقعی حذف نشدند و روی میزبان همچنان فعال‌اند. هیچ دادهٔ بازار ساخته نشد.
- یک اجرای میانی میزبان با تغییر موقت PaperAccount، تست حفظ هسته را شکست داد. تغییر هسته برگشت داده شد؛ کنترل موعد در مرز opt-in مستقل ماند. این آزمون حفاظت حذف/ضعیف نشد.
- JUnit نخست Clone به‌علت خطای مسیر نسبیِ Move-Item حفظ نشد و اجرای دوم آن را overwrite کرد؛ شمارش نخست از خروجی واقعی ثبت‌شده است، نه بازسازی نتیجه. این محدودیت در fresh_clone_initial_failures.json آمده؛ JUnit اجرای دوم و نهایی موجودند.

تست‌های جدید ۲۱ قرارداد غیرمالی/امنیتی‌اند: مرز ساعت، DST، clock fail-closed، ساعت سرور جلوتر، ابطال watchdog متوقف‌شده، metadata UNKNOWN/partial/cancel، idempotency، سفارش متضاد، Host، export allowlist، منع POST و عدم خواندن فایل کلید. status metadata، آزمون Fill صرافی نیست.

## اجرای داور و رابط

```powershell
conda run --no-capture-output -n shbk python scripts/judge_preflight.py
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
conda run --no-capture-output -n shbk python -m pytest -q
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_console --port 8766
```

برای Clone تازه از محیط جدا و requirements-judge-lock.txt روی Windows/Python3.12 استفاده شود؛ نبود archive/checkpoint مجاز و طبیعی است. روش تأمین عمومی data-sync-plan/run در JUDGE_QUICKSTART آمده است. هیچ وزن ناشناس، دادهٔ نمونه یا Session قدیمی با source جدید بارگذاری نشود. --help واقعی atlas_intelligence، m8_evaluation و m8_report بررسی شد؛ فرمان‌های تاریخی بدون source منجمد باید fail-closed شوند، نه اینکه برای نمایش Demo از آن عبور کنیم.

UI: http://127.0.0.1:8766 فقط READ_ONLY، فارسی/انگلیسی و با همان stdlib HTTP/HTML/CSS/Canvas قبلی. آزمون واقعی مرورگر شامل نمای کلی، جست‌وجوی Pattern، پنج مدل، خبر/مجوز NC، خطوط نرمال‌شدهٔ پنج همسایه، کندل بسته/تکنیکال/عمق واقعی آرشیوی و زبان بود. تصویر واقعی در reports/ui_overview.png ذخیره شد؛ نمونهٔ ساختگی نیست. آزمون جدا روی دستگاه موبایل ادعا نمی‌شود، فقط breakpoint واکنش‌گرا پیاده شده است. مهارت Computer Use برای تأیید بصری، جست‌وجو و تغییر زبان به کار رفت؛ طراحی فقط با HTMLخوانی تأیید نشد.

۳۶ ورودی قابل جست‌وجو:۲۰ ماژول CLI/service +۶ ابزار MCP +۱۰ ابزار ثبت‌شدهٔ Atlas. زیر‌فرمان‌های CLI در کارت‌ها expand می‌شوند. ابزار فاقد argparse با SERVICE_NO_HELP مشخص است. کلیک، shell یا MCP/private API اجرا نمی‌کند؛ UI هیچ Start/Stop/LIVE صوری ندارد. کنترل فرآیندهای مجاز از CLI foreground و Ctrl+C است. Snapshotها تاریخی‌اند؛ expiry پیش‌بینی‌ها بدون دستکاری Ledger نمایش داده می‌شود. نبود سفارش واقعی به‌معنی صفر سفارش فرض نشده است. حساب واقعی، PnL و credit تأییدنشده null می‌مانند.

## موعد و LIVE

جمعه ۲۳ اکتبر ۲۰۲۶، ۲۳:۵۰ Asia/Tehran =۲۰:۲۰ UTC =۲۲:۲۰ Berlin. ورود جدید از ۲۲:۵۰ ایران ممنوع، فاز خروج از ۲۳:۰۰، halt از ۲۳:۵۰. جدول مرزها و DST با ساعت‌های غیرمالی تست شد. لحظهٔ گزارش هنوز collecting بود، اما این نام فاز به معنی مجوز معامله نیست.

clock-check عمومی و watchdog محدود واقعاً اجرا شدند و HTTP Date قابل قبول در همان نمونه مشاهده شد. watchdog دائم یا Windows Task Scheduler نصب/فعال نشده است؛ پس از آزمون متوقف و permission receipt آن باطل شد. UI مستقل از آن است. در صورت نیاز اپراتور باید دستور زیر را آگاهانه برای root حساب پژوهشی صحیح اجرا کند:

```powershell
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_deadline watchdog --root atlas_store
```

gate ساعت تازه و اختلاف امن می‌خواهد و در هر تغییر مالی opt-in دوباره موعد را می‌سنجد؛ از ساعت دیرترِ محلی/سرور برای جلوگیری از تأخیر در halt استفاده می‌شود. این نسخه transport تسویه یا cancel صرافی ندارد. بعد از deadline حتی فروش residual خودکار نیست؛ هشدار `UNLIQUIDATED_RESIDUAL_MANUAL_REVIEW` برای موقعیت مشاهده‌شده و هشدار بررسی انسانی برای حساب نامعلوم ثبت می‌شود. فروش کامل تضمین نشده است.

کلید WALLEX_API_KEY در محیط بررسی موجود نبود؛ pass.txt و .env خوانده نشدند. هیچ private API call انجام نشد. مسیر مجاز read-only آماده است و redirect را دنبال نمی‌کند؛ پاسخ خصوصی اگر بعداً اپراتور اجرا کند فقط در atlas_store محلی می‌ماند. **اعتبار پنج میلیون مسابقه تأیید نشده**؛ پنج میلیون Shadow مقدار فرضی است.

LIVE = HARD_DISABLED، ARM عمداً موجود نیست. موارد باز: هویت اختصاصی contest، credit و package، allowlist برگزارکننده، fee واقعی، tick/step/min notional، حقوق سفارش API، self-trade چندحسابی، live transport و reconciliation/partial/cancel واقعی، positive financial Shadow E2E، مزیت اقتصادی مستقل و تأیید آگاهانهٔ مختص Session. ADD همچنان با Gate مسدود است. آزمون metadata یا cash-only این موانع را حل نمی‌کند. حساب شخصی/leveraged/margin جای حساب مسابقه قرار نگرفت.

## فایل‌های شاخص و خروجی

README.md/README_FA.md؛ JUDGE_QUICKSTART_FA/EN؛ ARCHITECTURE_FA، MODEL_CARD، MODEL_AND_SIGNAL_EXPLAINABILITY_FA، DECISION_TRACE، TOOL_INVENTORY، REPRODUCIBILITY، THIRD_PARTY_ATTRIBUTION، LIMITATIONS_AND_RESULTS، SHADOW_LIVE_BOUNDARIES_FA، TRADING_DEADLINE_1405_08_01_FA، UI_USER_GUIDE_FA. معماری M8 و اسکریپت Demo قبلی حفظ و با این Runbook تکمیل می‌شوند. FinBERT NC به مسابقه/سفارش وصل نشد؛ صفر کد معاملاتی ثالث کپی شد. SciPy مستقیم از اقتباس workflow و مطالعهٔ مفهومی جداست.

تمام JSONهای الزامی درخواست تولید و parse شدند: github_publish_audit، secrets_scan، fresh_clone_test، model_inventory، tools_inventory، judge_reproducibility، ui_smoke، live_readiness، deadline_dry_run، m8_followup_test_results و rubric_300_evidence. JUnitها، manifest comparison و preservation audit نیز تحویل‌اند. گزارش GitHub snapshot hash کدِ بررسی‌شده را ثبت می‌کند؛ commitهای بعدی اسناد نیز جدا Push/تطبیق می‌شوند. امتیاز مسابقه یا PnL جعل/تخمین نشده، ویدئو ضبط/ارسال نشده و پژوهش۴۸ساعتهٔ ناکامل تکمیل‌شده نامیده نشد.
