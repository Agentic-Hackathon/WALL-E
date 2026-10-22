# گزارش Milestone 3 — Feature Engineering پیشرفته و آمادگی مستقل هر بازار

## تغییر واقعی

- `atlas_feature_registry.py` یک registry پژوهشی V3 با **۵۲ ویژگی** نسخه‌دار ایجاد می‌کند: Trend (SMA/EMA/WMA/DEMA/TEMA/HMA، MACD، ADX/DI، Aroon، SuperTrend، Ichimoku، SAR، Donchian)، Momentum، Volatility، Volume، Price Action، Microstructure و Cross-Asset.
- برای هر تعریف، فرمول، خانواده، ورودی، timeframe، lookback/warmup، سیاست candle بسته، Missing/zero-denominator و hash پیاده‌سازی ثبت شده است. V1 Champion و V2 Challenger تغییر نکرده‌اند.
- محاسبهٔ V3 فقط بر OHLCV واقعی و hash-verified انجام می‌شود؛ division by zero، Infinity و warmup ناکافی به `NaN`/وضعیت صریح تبدیل می‌شوند، نه قیمت یا حجم ساختگی. VWAP با نام `typical_vwap24_approx_gap` صریحاً تقریب TP×volume است.
- Multi-timeframe `1m,5m,15m,30m,1h,4h,1D` با candle بسته و join backward-as-of بر `timestamp + candle duration` پشتیبانی می‌شود. Cross-asset BTC فقط با BTC/TMN واقعیِ هم‌زمان محاسبه می‌شود. Microstructure فقط mapping snapshot واقعی دارد و از OHLCV ساخته نمی‌شود.
- `DataSyncManager.feature_sync_plan` و `feature_readiness` نیاز registry را به target timeframe، source native و warmup تبدیل می‌کنند. بیش از ۷۲ ساعت (4h/1D) صریحاً report می‌شود و startup را به backfill پنهان تبدیل نمی‌کند.
- Watch از `all(...)` سراسری خارج شد: هر asset مستقلاً ready/not-ready audit می‌شود و فقط `allowed_symbols=eligible` به همان ShadowBroker/RiskGate موجود می‌رسد. اگر هیچ‌کدام آماده نباشد `NO_ELIGIBLE_MARKET_DATA` ثبت می‌شود.
- فرمان read-only جدید: `python -m wallex_bot.atlas_cli feature-audit-v3 --top 8 --output-dir reports`.

## اجرای واقعی و خروجی‌ها

روی هشت Spot/TMN با دادهٔ واقعی archive اجرا شد: `PEPETMN, BTCTMN, PUMPTMN, ETHTMN, USOONTMN, BNBTMN, USDTTMN, DOGETMN`.

- ۴ درخواست public محدود برای demand ویژگی `PEPETMN`: ۴ complete، صفر retry، صفر failure و صفر conflict. سپس فقط bucketهای کامل محلی materialize شدند.
- سلامت: ۲٬۶۲۴ ردیف؛ ۱٬۲۸۸ `MEASURED_REAL_CLOSED_CANDLES`، ۳۲ cross-asset PIT-aligned، ۱٬۲۸۸ timeframe مفقود/تأییدنشده و ۱۶ microstructure بدون snapshot time-matched واقعی.
- coverage: 1m/15m/1h برای ۸ بازار موجود؛ 5m/30m/4h/1D فقط برای PEPETMN پس از sync/materialization حاضر است. recipe کامل advanced برای ۰ از ۸ بازار آماده است؛ این fail-closed است، نه دادهٔ پرشده.
- ۶۴ زوج با correlation مطلق ≥۰٫۹۵ فقط برای review افزونگی ثبت شد. Ablation برای همه خانواده‌ها `INSUFFICIENT_VALIDATION_DATA` است؛ هیچ مدل تازه‌ای fit، promote یا جایگزین نشد.

فایل‌ها:

- `reports/feature_registry.json`
- `reports/feature_health.csv`
- `reports/feature_coverage.csv`
- `reports/multitimeframe_alignment.json`
- `reports/feature_redundancy.csv`
- `reports/per_asset_readiness.json`
- `reports/feature_sync_requirements.json`
- `reports/feature_ablation.csv`

## فایل‌های اصلاح‌شده

- `wallex_bot/atlas_feature_registry.py`
- `wallex_bot/atlas_feature_audit_v3.py`
- `wallex_bot/atlas_data_sync.py`
- `wallex_bot/atlas_watch.py`
- `wallex_bot/atlas_shadow.py`
- `wallex_bot/atlas_cli.py`
- `tests/test_milestone3_feature_registry_real_only.py`
- `tests/test_milestone2_1_data_sync_real_only.py`

## تست

```powershell
conda run -n shbk python -m pytest -q
```

نتیجه: `155 passed, 5 skipped`.

تست‌های جدید فقط registry، metadata orchestration، archive خالی و قراردادهای fail-closed را به کار می‌گیرند؛ candle، quote، order-book یا خبر ساختگی تولید نمی‌کنند. یک تست مشخص تأیید می‌کند که در حضور یک market ناسالم و یک market سالم، فقط asset سالم به مسیر Shadow موجود داده می‌شود.

## آنچه اثبات نمی‌شود

- این registry سود، دقت Transformer، کیفیت execution، یا مناسب‌بودن indicatorها برای معامله را اثبات نمی‌کند.
- 4h/1D در اغلب دارایی‌ها هنوز history کافی ندارد؛ API عمومی earliest history را تضمین نمی‌کند.
- Microstructure بدون snapshot واقعیِ time-matched عمداً missing می‌ماند.
- LIVE، سفارش واقعی، Champion، checkpointها و RiskGate تغییر نکرده‌اند.

## اثر و گام بعد

این milestone reproducibility/PIT، health visibility، جلوگیری از توقف غیرضروری Watch و demand-driven sync را بهتر می‌کند؛ نه معیار اقتصادی challenge را. اولویت Milestone 4: جمع‌آوری تدریجی receiptهای واقعی multi-timeframe و order-book، سپس ablation زمانی خارج از نمونه بدون promotion خودکار.

## Commit

commit اصلی: `4a808d7119dd45b74f9b930dd4517da7b08da9ac` (`feat: add per-asset feature readiness and registry`).
