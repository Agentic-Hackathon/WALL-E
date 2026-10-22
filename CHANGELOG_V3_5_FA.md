# V3.5 — Local Research and Shadow Dashboard

- Milestone 3: registry پژوهشی V3 با ۵۲ feature، محاسبهٔ PIT-safe چندتایم‌فریمی، health/coverage/redundancy reports، نیاز warmup متصل به DataSync و readiness مستقل هر market در Watch افزوده شد؛ Champion، RiskGate و LIVE تغییر نکردند.

- Milestone 2.1: `DataSyncManager` برای sync محدود و resumable هنگام startup/Watch، plan/status/run CLI، lease SQLite، fail-closed شدن Agent/Watch روی دادهٔ نامعتبر و بررسی حساب read-only افزوده شد؛ LIVE، Champion، Risk Gate و Transformerها تغییری نکردند.

- Risk Gate مستقل و قطعی `atlas_risk.py` اضافه شد؛ تمام intentهای Shadow پیش از هر تغییر دفتر از همین دروازه عبور می‌کنند، با سقف‌های قبلی، بررسی نقدشوندگی/اسپرد واقعی، stop-loss و circuit breaker. این تغییر همچنان هیچ سفارش واقعی ارسال نمی‌کند.

- Added zero-external-CDN, no-new-dependency RTL dashboard at `127.0.0.1:8765`.
- Added safe, read-only JSON endpoints for status, actual SHA256-verified OHLCV candles, recorded forward forecasts, paper trade ledger, news receipts, historical strategy benchmark, read-only account balances, and retrospective research.
- Added candlestick visual including real time gaps, SMA20 only across contiguous actual bars, interactive hover and 20-second refresh.
- Added clear segregation between real account balances (unverified contest account), paper portfolio, paper orders and forecasts.
- Added `run_research_snapshot.sh`: train-only-selected technical backtests and strict post-Champion-promotion model diagnostics. No use of model-selection period as independent economic proof.
- Avoided hypothetical news impact claims; news input to current Champion explicitly false.
- Added new no-price-fixture tests for no fabricated evidence and HTTP safety.
- No changes to watch loop, strategy gates, models, existing data archives, private keys or production order availability.
- Explicitly displays remaining integration gaps: news is not in DL features; full LangGraph orchestration and indicator vetos are not in the foreground `watch` path.
