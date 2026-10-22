# Market data — read-only skill
Purpose: select real Wallex spot market observations relevant to the requested horizon.
- Discover symbols from actual catalog. Only approved markets may ever be considered for contest orders.
- Read completed genuine candle segments and actual bid/ask quotes; keep original source timestamps and SHA-256 evidence references.
- Never fill, interpolate, backdate, fabricate, or silently stitch missing bars.
- Distinguish observed minute candles from hourly/native and derived bars; verify bar spacing.
- The latest data may be stale. With insufficient evidence report missing data; do not guess.
- Archive all markets independently of the short-horizon contest shortlist.
