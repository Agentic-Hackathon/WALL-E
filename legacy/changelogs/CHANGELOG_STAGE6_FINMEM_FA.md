# Stage 6 — PIT evidence memory selection (FinMem-inspired)

- **Base:** `integration/atlas-mode-isolation`, commit `250f342` (user local).
- **Concept source:** FinMem (Yu et al.), `pipiku915/FinMem-LLM-StockTrading`, pinned commit `be814aa47970de9bf2fdd6a1d5a60ae5cf361b46`, MIT according to `third_party/SOURCES.md`; code independently written; no third-party copying.
- **Changes:** `wallex_bot/atlas_memory.py` deterministic ranking, `atlas_context.py` strict point-in-time evidence view, `atlas_agent.py` symbol-scoped context, `atlas_cli.py` command `memory-rank`, new metadata-only tests.
- **Score:** `exp(-ln(2)*age_hours/24) * bounded_importance * schema_relevance`, capped candidate scan 2000 and top-K 40; HOT <=6h, WARM <=72h, COLD >72h. NOT official FinMem formula or trained weights.
- **Trust model:** only structured operational evidence (with hash-chain verification) is retrieved; headlines, prompts, lessons, model weights and order authority are never retrieved or altered. `BACKTEST` cannot read production operational memories even when given historical as-of. `LIVE` remains completely disabled.
- **Read-only CLI:** `python -m wallex_bot.atlas_cli memory-rank --top 12 --symbol BTCTMN`; absent DB remains absent.
- **Not proven:** stronger trading returns, better predictive performance, safer real exchange execution, verified exchange fees or genuine contest PnL.
- **Next:** advisory LLM rationale with hash-keyed caching, then deterministic replay; no trade eligibility promotion until independent OOS evidence.
