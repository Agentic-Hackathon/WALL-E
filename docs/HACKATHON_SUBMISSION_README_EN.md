# Wallex Atlas — Milestone 8 research submission

This is an opt-in Shadow research integration, not verified profitable trading or live authorization. The existing Champion, Transformers and RiskGate remain intact. LIVE is HARD_DISABLED. No private endpoint or exchange order is required.

Run from the repository root in the existing `shbk` environment:

```powershell
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_intelligence status
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_intelligence run
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_intelligence replay
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m8_report
```

The collector is foreground-only. Stop it normally and resume with the same command; offline gaps are never backfilled with invented quote observations. Source, checkpoint or dependency changes require a new frozen session. `requirements-m8.txt` records the observed environment; installation in a fresh environment has not been demonstrated. Real archive/catalog/checkpoints matching the manifest are required; they are not replaced with fixtures or bundled fake weights.

An identical session also requires existing local helper scripts hashed by the source manifest, including the user's untracked `scripts/apply_broker_stage2.sh` and `scripts/export_committed_risk_stage.sh`. They were preserved, not silently added to Git. A clean clone alone is therefore not a demonstrated reproduction of this exact frozen workspace. Preserve matching local inputs or prepare a new separately pinned session for a clean package; second-machine installation was not tested.

The implementation has ten structured specialist roles in four executable LangGraph nodes, not ten LLM calls. Actual Champion quantiles constrain decisions before explanations. Historical analogues use SciPy distances and independently authored bounded DTW, with hash, availability, embargo and temporal de-overlap checks. No external framework performance is presented as an Atlas result.

Limitations: pattern/news/memory economic value remains unverified; cached FinBERT has a non-commercial license and is not used to authorize contest decisions; shared historical PIT news samples are insufficient. ADD is blocked by the unchanged RiskGate. Rebalancing requires separately gated legs, never a fabricated atomic fill. Actual approved entries/held exits were not available to validate financial execution branches. The fee is an explicitly unverified .001 per-side assumption. A 48-hour protocol is not 48 hours of completed observation. Recorded-decision replay is not an independent long-history economic backtest. See the Persian milestone report and machine-readable artifacts for actual counts and unresolved requirements. No automatic promotion, publication, competition submission or video recording was performed.
