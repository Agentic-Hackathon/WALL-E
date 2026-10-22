# منابع بیرونی

کلون‌ها فقط برای مطالعه هستند و در پکیج `wallex_bot` وارد نمی‌شوند. وضعیت مجوز
قبل از هر استفاده از کد باید بررسی شود. در این مرحله، هیچ کد خارجی کپی نشده است.

| ریپو | commit | لایسنس | استفاده |
|---|---|---|---|
| https://github.com/Ajay03299/hindsight | `5111eeaf969c26c74443f5fd1d5dfbd30b32a9af` | MIT (متن LICENSE با جای‌نگهدارندهٔ copyright) | مطالعهٔ اعتبارسنجی؛ کد در این مرحله کپی نشده است |
| https://github.com/yashdhingra0/trading-bot | `688087e64f79f545c7e40ee6e889c9ce92e03693` | نامشخص؛ فایل LICENSE/LICENCE/COPYING یافت نشد | فقط ایدهٔ «risk-first»؛ کد از صفر نوشته می‌شود |
| https://github.com/jordantete/grid_trading_bot | `fbda3dd5558a168f11e1a9733e12e1d9d8b3e1fc` | MIT (`LICENSE.txt`) | مطالعهٔ retry/circuit-breaker؛ کد در این مرحله کپی نشده است |
| https://github.com/pipiku915/FinMem-LLM-StockTrading | `be814aa47970de9bf2fdd6a1d5a60ae5cf361b46` | MIT | مطالعهٔ حافظهٔ لایه‌ای؛ کد در این مرحله کپی نشده است |
| https://github.com/CuongMe/QuantCrypt | — | unavailable (Repository not found) | هیچ کدی در دسترس/استفاده نشده؛ ایدهٔ جداسازی mode بعداً از صفر پیاده می‌شود |
| https://github.com/TauricResearch/TradingAgents | `e8f5503e9b86d5c2710b0c76b1f686703968c9df` | Apache-2.0 | مطالعهٔ ساختار نقش‌ها؛ کد در این مرحله کپی نشده است |
| https://github.com/Lumiwealth/lumibot | `b529372528d2a1bba7f0f5e0183f6b4be8de1d7c` | GPL-3.0 | فقط مطالعهٔ مفهومی؛ هیچ کدی کپی یا مشتق نمی‌شود |
| https://github.com/AI4Finance-Foundation/FinRL-Trading | `4409abe925c904e570be78ebfb5e77ac3491dff8` | Apache-2.0 | مطالعهٔ risk overlay/target weight؛ کد در این مرحله کپی نشده است |

## Milestone 4 — مدل خبری پژوهشی

- Model: `ProsusAI/finbert`, revision `0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031`؛ model card رسمی: https://huggingface.co/ProsusAI/finbert/blob/0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031/README.md
- مجوز وزن‌ها در model card: **CC-BY-NC-SA-4.0**؛ مدل فقط در پژوهش محلی و مسیر مشاوره‌ای استفاده شده است. این ثبت به معنی احراز مجوز استفادهٔ مسابقه/تجاری نیست.
- safetensors SHA-256: `e5897858ff819aad7629b96ce521ae5477952d03634ef5dd30ed2d76357a9f00`؛ tokenizer و config نیز با hash در receipt مدل ثبت می‌شوند. هیچ وزن مدلی در Git commit نمی‌شود.
- مدل انگلیسی است؛ عنوان‌های فارسی/زبان نامطمئن خودکار به آن فرستاده نمی‌شوند. خروجی تخمین مدل است، نه برچسب حقیقت.
- از `requests`، `langdetect` و `transformers` نصب‌شده استفاده شد؛ کد ثالث کپی نشد. طراحی NewsStore و PIT به‌صورت مستقل روی archive/RSS و حافظهٔ داخلی موجود نوشته شد.

## Milestone 5 — DLinear reference

- Repository: https://github.com/cure-lab/LTSF-Linear
- HEAD inspected: `0c113668a3b88c4c4ee586b8c5ec3e539c4de5a6` (public `git ls-remote`, 2026-10-22).
- License read at that revision: [Apache-2.0](https://github.com/cure-lab/LTSF-Linear/blob/0c113668a3b88c4c4ee586b8c5ec3e539c4de5a6/LICENSE).
- Actual source inspected: `models/DLinear.py`; moving-average decomposition and separate linear trend/residual maps. No source copied, no external repository executed.
- Atlas `DLinear_ridge` independently implements the decomposition idea with a 25-point endpoint-padded moving average inside the observed window, scalar **log-return** target and train-only ridge fit. This differs from the reference's multistep price target and SGD; it is not claimed as a paper reproduction.
- Existing Atlas `atlas_deep.py` backbones, V1/V2/V3 feature recipes, verified archive reader, DataSyncManager, BACKTEST memory and news contracts are reused unchanged. New M5 orchestration/training/calibration/report code is independently authored.
- Existing installed LightGBM quantile estimator and scikit-learn Ridge are used through public interfaces; no implementation copied. FinBERT remains research/advisory-only under the M4 license restriction; M5 trained no news model.

## Milestone 6 — conceptual references, no copied implementation

All seven repositories were inspected, with LICENSE read before implementation. Existing Atlas modules were extended rather than importing another trading framework. No code from these repositories is executed by Atlas.

| Repository | Inspected commit | License | Inspected capability and Atlas use |
|---|---|---|---|
| TradingAgents | `e8f5503e9b86d5c2710b0c76b1f686703968c9df` | Apache-2.0 | `tradingagents/graph/trading_graph.py`: role separation; seven structured deterministic review roles inside existing LangGraph. Concept only. |
| FinMem | `be814aa47970de9bf2fdd6a1d5a60ae5cf361b46` | MIT | `puppy/memory_functions/compound_score.py`: layered evidence ranking. Atlas retains its own bounded product score, not FinMem's additive formula. Additive tables in ContextStore. |
| Hindsight | `5111eeaf969c26c74443f5fd1d5dfbd30b32a9af` | MIT with placeholder copyright | `WRITEUP.md`: leakage, null/baseline and regime skepticism. Prospective partition distinct from M5 results; no claimed repo profits adopted. |
| FinRL-Trading / FinRL-X | `4409abe925c904e570be78ebfb5e77ac3491dff8` | Apache-2.0 | `src/strategies/adaptive_rotation/risk_manager.py`: global state/stop separation; existing RiskGate unchanged, isolated 5M Shadow portfolio. No DRL or source code ported. |
| https://github.com/nautechsystems/nautilus_trader | `a51ae015c150ef68f62d9295e3efa9534f492a4a` | LGPL-3.0 | `crates/event_store/src/replay.rs`: state-only replay without publishing commands. Concept only; no LGPL code copied. |
| https://github.com/freqtrade/freqtrade | `c051e9065c5b677f03817dd1f83cb980af1ed684` | GPL-3.0 | `docs/lookahead-analysis.md`: prefix/truncated input comparisons. Concept only; no GPL code copied; risk protections are NOT disabled. |
| https://github.com/hummingbot/hummingbot | `9af100d6822da7d2d0291a906c730ef172284ee2` | Apache-2.0 | `hummingbot/connector/client_order_tracker.py`: stable identities and reconciliation. Atlas already has an order tracker; only observation identity/lease/reconcile extended. No connectors copied or enabled. |

The last three references are shallow, filtered sparse checkouts under third_party. Paths were discovered using Git tree listings, not guessed. License bytes/commit/path evidence are exported in reports/m6_reference_repositories.json. No futures, leverage, short or withdrawal code was imported.

## Milestone 7: allocation, costs and formal prospective protocol

Same pinned commits/licenses as M6 above; no external source copied or executed.
Discovered and inspected FinRL-X `src/strategies/adaptive_rotation/portfolio_builder.py`
(4409abe925c904e570be78ebfb5e77ac3491dff8, Apache-2.0): target weights/cash residual
separate from execution. Independently authored `atlas_portfolio.py` retains the Atlas gate.
Discovered and inspected Hummingbot `hummingbot/core/data_type/trade_fee.py`
(9af100d6822da7d2d0291a906c730ef172284ee2, Apache-2.0): explicit fee impact vs returns;
no connectors, private requests or external trading code imported. Existing Atlas
`live_scout.measure_book`, `_buy_with_notional`, `_sell_qty` reused for real depth estimates.
NautilusTrader LGPL-3.0 state-only replay and Freqtrade GPL-3.0 lookahead concepts
remain idea-only; no license-restricted code copied. FinMem MIT research evidence
layers reused through existing Atlas ResearchMemory with actual creation/PIT cutoffs.
No new framework, portfolio optimizer or external performance claim adopted.
Per-file license hashes verified again in `reports/m7_reference_integration.json`.

## Milestone 8: actual numerical reuse for historical analogues

`atlas_patterns.py` directly calls installed SciPy 1.16.3
`scipy.spatial.distance.cdist` (BSD-3-Clause) rather than reimplementing
pairwise Euclidean distances. This is executable library reuse, not a claim
that one of the trading frameworks was imported.
Existing local librosa 0.10.2.post1 (ISC LICENSE.md read completely) was
investigated for its constrained DTW API. The local import/inspection probe
did not finish within several minutes and was interrupted; no successful
runtime integration is claimed. Primary algorithm/API documentation inspected:
https://librosa.org/doc/0.10.2/generated/librosa.sequence.dtw.html
Atlas implements only the small endpoint-anchored banded recurrence over
SciPy costs, independently authored, with explicit band=2 and n+m normalization.
No audio code, fitted encoder, external trading connectors or synthetic market
data are imported. Recipe, actual receipt availability, labels, embargo and
temporal de-overlap are Atlas-specific glue; historical close outcomes are
never described as order fills or trading PnL.

M8 agentic board adapts the TradingAgents structured critique workflow using
Atlas's own seven-role review and existing LangGraph/SqliteSaver, not the
TradingAgents runtime. Existing FinMem-inspired ResearchMemory and M7 capped
target-weight allocator are called functionally before the new Shadow adapter.
No FinMem additive score or trading framework was silently substituted.
All source comments distinguish independently authored adapters from direct
library integration. GPL/LGPL and unspecified-license clones remain study-only.

FinBERT's actual pinned local README.md was re-read: its front matter still
declares cc-by-nc-sa-4.0. M8 competition-facing news ingestion does not run it
and the decision board cannot apply its scores as a trading vote.
Candidate alternative reviewed (NOT downloaded or executed):
https://huggingface.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis/blob/main/README.md
declares Apache-2.0 but uses Financial PhraseBank. The dataset's own card
https://huggingface.co/datasets/takala/financial_phrasebank declares
CC-BY-NC-SA-3.0 and asks commercial users to obtain an appropriate license.
Therefore the candidate was not assumed cleared for contest use; no remote
accuracy/profit claims are adopted as Atlas results. Existing 14 news features
are wired into four local research arms with train-only scaling and a strict
data/availability guard, not fabricated neutral scores.
