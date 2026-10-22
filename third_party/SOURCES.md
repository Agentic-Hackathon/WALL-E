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
