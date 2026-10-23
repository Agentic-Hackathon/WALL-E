# Reference attribution — no framework profit claims

Sources below were inspected in previous milestones; exact LICENSE hashes are in reports/m8_reference_integration_matrix.json. No external trading repository source was copied or executed. Atlas-specific adapters are independently authored; SciPy is direct runtime reuse.

|Repository URL|Commit/version|License|Actual use / file & test|Restriction|
|---|---|---|---|---|
|https://github.com/TauricResearch/TradingAgents|e8f5503e9b86d5c2710b0c76b1f686703968c9df|Apache-2.0|Adapted critique workflow, atlas_agentic_review/cycle, test_milestone8_agentic_real_only|Not imported framework|
|https://github.com/pipiku915/FinMem-LLM-StockTrading|be814aa47970de9bf2fdd6a1d5a60ae5cf361b46|MIT|Adapted memory workflow, atlas_memory, test_stage6_pit_memory_real_only|Atlas product ranking, not copied additive score|
|https://github.com/AI4Finance-Foundation/FinRL-Trading|4409abe925c904e570be78ebfb5e77ac3491dff8|Apache-2.0|Adapted target-weight workflow, atlas_portfolio, test_milestone7_portfolio_real_only|No DRL/runtime framework|
|https://github.com/Ajay03299/hindsight|5111eeaf969c26c74443f5fd1d5dfbd30b32a9af|MIT, copyright placeholder|Concept: skeptical temporal validation|No copied implementation|
|https://github.com/jordantete/grid_trading_bot|fbda3dd5558a168f11e1a9733e12e1d9d8b3e1fc|MIT|Concept: circuit breaker/retry, atlas_broker|No copied implementation|
|https://github.com/yashdhingra0/trading-bot|688087e64f79f545c7e40ee6e889c9ce92e03693|Unspecified|Concept: risk-first|Copying blocked|
|https://github.com/Lumiwealth/lumibot|b529372528d2a1bba7f0f5e0183f6b4be8de1d7c|GPL-3.0|Concept only|No GPL code copied|
|https://github.com/freqtrade/freqtrade|c051e9065c5b677f03817dd1f83cb980af1ed684|GPL-3.0|Concept: prefix/lookahead tests|No protections disabled or GPL code copied|
|https://github.com/nautechsystems/nautilus_trader|a51ae015c150ef68f62d9295e3efa9534f492a4a|LGPL-3.0|Concept: state-only replay|No LGPL code copied|
|https://github.com/hummingbot/hummingbot|9af100d6822da7d2d0291a906c730ef172284ee2|Apache-2.0|Concept: identity/reconcile/fee impact|No connector enabled|
|https://github.com/cure-lab/LTSF-Linear|0c113668a3b88c4c4ee586b8c5ec3e539c4de5a6|Apache-2.0|Independent DLinear_ridge decomposition, atlas_m5_baselines|Not paper reproduction|
|https://github.com/scipy/scipy|installed1.16.3|BSD-3-Clause|DIRECT cdist, atlas_patterns, test_milestone8_patterns_real_only|No claimed economic edge|
|https://github.com/librosa/librosa|installed0.10.2.post1|ISC|Rejected runtime import probe; DTW docs studied|Independent bounded recurrence used instead|
|https://github.com/CuongMe/QuantCrypt|unavailable|Unknown|No code available|Repository not found|

FinBERT pinned card: https://huggingface.co/ProsusAI/finbert/blob/0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031/README.md — CC-BY-NC-SA-4.0 reported; weights excluded, contest decision use not authorized. Public publisher headlines are not republished as a synthetic dataset. Source reports contain provenance and research evidence, not a grant to redistribute restricted weights/text.

Security audit uses official Gitleaks8.30.1 (MIT), portable binary excluded from Git. Historical false positives are exact fingerprints verified as source/tokenizer SHA256; no broad generic-key rule suppression.
