# Spot release contract — 2026-10-23

Source: official [Wallex Spot documentation](https://developers.wallex.ir/docs/spot-create-order),
[order detail](https://developers.wallex.ir/docs/spot-single-order-detail),
[open orders](https://developers.wallex.ir/docs/spot-active-orders),
[cancel](https://developers.wallex.ir/docs/spot-cancel-order),
[public market metadata](https://developers.wallex.ir/docs/basic-services-markets),
[credit wallet](https://developers.wallex.ir/docs/trade-credit-wallet).
No external connector implementation was copied.

The reviewed contracts specify POST `/v1/account/orders`, GET/DELETE
`/v1/account/orders/{client_id}`, GET `/v1/account/openOrders`, string quantities
and prices, unique `client_id`, and cumulative fills with per-asset fees.
**Only GET is implemented in the new release transport. No POST or DELETE was
performed.** It is not a completed live trader.

The docs use FINISHED in cancellation prose and FILLED in other examples.
`SpotLedger` therefore requires exact cumulative execution quantities and
complete matching fill details. Unrecognized/missing fields fail closed.
An empty open-order list is not proof of completed settlement. Fees in different
assets are never summed as if all were TMN; actual balances require a separate
read and account-specific conservation check.

Public amount/price precision is not proof of tick, step, minQty or minNotional.
These verified limits must be supplied to exact serialization; no defaults or
automatic rounding create an executable order. Ordinary balance cannot certify
contest identity, contest credit or API trade permissions. Account/subaccount
routing and package constraints must be verified before releasing mutation.

## Explicitly open work

1. Independently verified contest account, package ID, allowed markets, credit,
   fees, limits and account-scoped key/routing.
2. Fresh account/balance/open-order reconciliation and conservative real NAV,
   risk context and forecast provenance for every financial action.
3. Authenticated POST/DELETE adapter with no redirect/retry, atomic outbox,
   restart-safe UNKNOWN handling and exchange response recordings.
4. Local operator arm bound to process/session, exact symbols, capital limit
   and expiry; restart must disarm. No environment boolean may replace it.
5. Positive authorized real-account execution tests for buy/sell, partial fill,
   cancellation races, actual fees and cash/position conservation.
6. Independent net out-of-sample edge evidence; no threshold relaxation.
7. Deployment of the deadline supervisor and authenticated order integration;
   current supervisor observes only and is not an automatic liquidation service.

Until reviewed separately, submit/cancel always raise a safety error, no
LIVE_READY/LIVE_ARMED state is granted, and existing brokers remain unchanged.
READ_ONLY/SHADOW/LIVE_PREFLIGHT/LIVE_READY/LIVE_ARMED/EXIT_ONLY/HALTED/BLOCKED
names are declared, but declaration is not implementation of an arming workflow.
