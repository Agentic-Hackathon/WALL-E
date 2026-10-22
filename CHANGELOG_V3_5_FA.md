# V3.5 — Local Research and Shadow Dashboard

- Added zero-external-CDN, no-new-dependency RTL dashboard at `127.0.0.1:8765`.
- Added safe, read-only JSON endpoints for status, actual SHA256-verified OHLCV candles, recorded forward forecasts, paper trade ledger, news receipts, historical strategy benchmark, read-only account balances, and retrospective research.
- Added candlestick visual including real time gaps, SMA20 only across contiguous actual bars, interactive hover and 20-second refresh.
- Added clear segregation between real account balances (unverified contest account), paper portfolio, paper orders and forecasts.
- Added `run_research_snapshot.sh`: train-only-selected technical backtests and strict post-Champion-promotion model diagnostics. No use of model-selection period as independent economic proof.
- Avoided hypothetical news impact claims; news input to current Champion explicitly false.
- Added new no-price-fixture tests for no fabricated evidence and HTTP safety.
- No changes to watch loop, strategy gates, models, existing data archives, private keys or production order availability.
- Explicitly displays remaining integration gaps: news is not in DL features; full LangGraph orchestration and indicator vetos are not in the foreground `watch` path.
