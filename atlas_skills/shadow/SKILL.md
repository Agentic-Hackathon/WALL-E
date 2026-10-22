# Shadow evaluation — observation-only skill
Purpose: evaluate hypothetical actions with actual exchange observations.
- Record complete model, quote and risk evidence. Never construct fake market prices or synthetic fills.
- A hypothetical fill at observed top-of-book is not an actual fill or realizable PnL.
- Score forward predictions only when a genuinely future quote is received at the correct time.
- Keep stable session identifiers across restarts; report missing intervals rather than backfill.
- Maintain independent decision, outcome and shadow portfolio ledgers.
