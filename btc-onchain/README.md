# Bitcoin on-chain data — source quality, independent cost basis

These collectors are **not trading signals**. The hourly BTC monitor reads
`btc-onchain/data/monitor_latest.json` through the quality bridge
`btc-monitor/data/brief.json`. A fresh JSON creation timestamp alone
does not make a delayed daily on-chain indicator current.

## Independent fresh cost-basis series

Bitview public UTXO-day series, tracked at `btc-onchain/data/bitview_latest.json`
and stored with history in `bitview_history.json`, offers:

* `realized_price_bitview` — network-wide Bitcoin UTXO realized price.
* `sth_realized_price_150d` — UTXO short-term (<150 days) cost basis.
* `lth_realized_price_150d` — UTXO long-term (>=150 days) cost basis.

These public series had verified measurements for **2026-11-01** on
2026-11-02. They have their own dates, source, and methodology; under no
circumstances substitute them into the original keys without renaming.

In the bridge, the three distinct fields are exposed under
`onchain_cost_basis_independent`, with `status=usable` only when the
original composite feed is fresh, Bitview's inner component is not older than
30 hours at generation, the metric observation is <=3 days old and numerical.
The monitor also has an explicit readiness flag
`family_readiness.onchain_independent_cost_basis`.

## Original data limits

The BGeometrics free original `realized_price` and `sth_realized_price`
were dated 2026-10-26 while independent Bitview was dated 2026-11-01.
The original `lth_realized_price` had not yet been downloaded. A real
one-off public API probe at `btc-onchain/data/bgeometrics_probe.json`
established HTTP 200 and **7 dated rows through 2026-10-26** for all three
original documented public endpoints. Thus the missing original LTH source
was not a non-existent API; the collector now prioritizes it in its
existing optional request slot, keeping **10 requests per daily run**
within both free plan limits (**10 per hour and 15 per day**). The first
attempt to send 11 requests in one hour correctly produced HTTP 429;
the budget was then fixed, with code-push CI changed to run tests only
so it cannot repeatedly consume the free allowance. After genuine
LTH checkpoint retrieval the optional rotation resumes. If the source
continues to publish 7 days
late, this **cannot be repaired by repeated requests**. Old observations
remain labelled delayed and are never published as fresh.

The original collector runs at
`.github/workflows/btc-onchain-history.yml`. Its quota/rotation tests
precede collection. The other on-chain metrics, including holder behavior,
MVRV and exchange flows, retain their independent sourcing.

## Cross-source quality control

`btc-onchain/realized_audit.py` performs **no additional external API
requests**. It compares only observations already present for the same UTC
date in `history.json` and `bitview_history.json`, publishing a daily
`btc-onchain/data/realized_audit.json` from
`.github/workflows/btc-onchain-realized-audit.yml`.

The last common day at the initial reconciliation, 2026-10-26, differed
by ~0.0441% for network realized price and ~0.1307% for STH (differences
are expected between vendors and age-cohort methodologies). An exact
BGeometrics LTH historical cross-check was unavailable then.

The Bitview 150d cohort is **not** automatically equivalent to a
155-day/entity-weighted provider series. Do not aggregate or count
dependent holder-cost-basis metrics as independent trend-confirmation
factors. An empty original series remains missing; a delayed series
remains delayed; a plausible proxy is explicitly separate.
