# Stage 4 — اعتبارسنجی پژوهشی واقعی؛ بدون معامله

**Baseline commit:** `1f43a04`، branch `integration/atlas-tmn-liquidation`.

- Added `wallex_bot/atlas_validation.py`: genuine archived Wallex candles, verified-by-SHA Lake.load, train-selected technical candidate / strictly later chronological holdout, and buy-and-hold, seeded random-actions and independent ridge DLinear-inspired baseline on the same observed data.
- Added Deflated Sharpe diagnostic on disjoint TRAIN blocks using archived nominal search trial count (not an effective independent-trials estimate), and CSCV/PBO **entirely inside TRAIN**. Missing candidate ledger or insufficient blocks => `INSUFFICIENT_EVIDENCE`, never invented metrics.
- Added CLI `python -m wallex_bot.atlas_cli validate` writing **only** `atlas_store/reports/stage4_validation.json`.
- Fixed early no-op paper closeout: with a persisted watch session AND an already-flat verified paper ledger, `liquidate-paper` returns `ALREADY_FLAT` before the deadline. Without any session, Stage3's fail-closed exception and no-file-creation contract remain unchanged. **Open positions still require the actual validated deadline.**
- New contract tests create no prices, OHLCV, external news, simulated market outcomes or real orders.

## منابع و مجوزها

- **Hindsight** `Ajay03299/hindsight`, commit `5111eeaf969c26c74443f5fd1d5dfbd30b32a9af`; MIT according to existing `third_party/SOURCES.md` (license contains copyright template). Concepts only; no code copied.
- Bailey & López de Prado, *The Deflated Sharpe Ratio*, J. Portfolio Management 2014, DOI `10.3905/jpm.2014.40.5.094`.
- Bailey, Borwein, López de Prado, Zhu, *The Probability of Backtest Overfitting*; DOI `10.21314/JCF.2016.322`.
- Zeng et al., *Are Transformers Effective for Time Series Forecasting?*, DLinear; independent minimal linear decomposition baseline, **not** an official model implementation or paper result.

## محدودیت‌ها

- No actual user's `atlas_store` present in this development environment. The **real numerical validation result remains unknown**, and must be run on their machine.
- Open-price entry/exit after decision uses **real observed** candles but is still a hypothetical fill (no depth/order-book guarantee).
- Fee and slippage are default research assumptions (`0.001` and `0.0005` each side), **not verified Wallex package costs**.
- Nominal global number of rows in previous strategy CSV is not effective number of independent trials; resulting DSR is approximate with correlated candidates, especially when sample is short.
- PBO is an in-sample CSCV selection instability diagnostic, **not** forward profits. Holdout is strictly chronological for economic evaluation.
- Random baseline invents **decisions only**, never prices or outcomes. Decomposition baseline predicts future close-to-close but is executed hypothetically next open; not fully equivalent to Transformer model.
- No comparison with champion after promotion without genuine forward snapshots; does not change `active_champion.json` or loosen RiskGate.
- Does **not** improve proven profit or confirm challenge readiness; stage 4 primarily targets reproducibility 25, strategy rationale 40 and shadow/backtest 20 points, subject to judge review.
