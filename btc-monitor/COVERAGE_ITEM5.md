# BTC market-data coverage — item 5 source-capability closeout

## Acceptance and evidence

The **selected 11 real LIVE BTC spot/perpetual venues** are verified with their own named instrument and timestamp. Availability of the exchange/orderbook snapshot **does not** establish complete depth at 0.2% or 1% of its own midpoint. Source-boundary checks, bid/ask reach, market type and quote units must be individually valid.

The machine-readable per-market/per-band receipt is
[`btc-monitor/data/coverage_latest.json`](data/coverage_latest.json), rebuilt on every successful
[`btc-monitor-bridge.yml`](../.github/workflows/btc-monitor-bridge.yml).
The primary outputs are still `btc-monitor/data/brief.json` and
`btc-monitor/data/metric_quality_acceptance.json`. The brief now separately reports
`orderbook_live.complete_markets_by_band.{0.01,0.05,0.2,1.0}` and
`all_11_markets_complete_1pct`. **No current or past coverage count should be considered timeless**.

The initial genuine item 5 acceptance at **2026-11-02 21:06 UTC** saw both-sided complete
depth at 0.01% and 0.05% for all 11 markets, at 0.2% for 7/11, and at 1% for 1/11.
These are instantaneous facts, not long-run coverage guarantees. Complete-band counts can
increase or decrease with the actual native depth of the exchange's book.

## Official-source maximum depth and actual runtime probes

| Instrument/source | Official access outcome | Safe treatment |
|---|---|---|
| Bybit Spot BTCUSDT | Official native WS `orderbook.1000.BTCUSDT` working. Official new full REST `/v5/market/full_orderbook` (up to **10,000** native levels) **403** from GitHub Actions: CloudFront country restriction | Keep official WS 1,000-level snapshot. Its 1% band is `null` until genuinely covered; do not replay blocked REST or use a geo-proxy/another exchange. |
| Bybit linear BTCUSDT perpetual | Same real native WS 1,000-level depth works; official full REST **403** from GitHub Actions | Same fail-closed policy, separate perpetual instrument |
| Binance USD-M BTCUSDT perpetual | Official WS depth API request allows **at most 1,000** per side (documented maximum); live 1,000 verified | A band extending beyond the actual 1,000 native levels remains unknown |
| OKX spot/perpetual BTC-USDT | Discovered **official free** `GET /api/v5/market/books-full?instId=...&sz=5000` (5000 levels per bid/ask side), previously omitted by the collector using 400-level `books`. First successful production check on 2026-11-02 21:28 UTC returned 5000 levels each side for BOTH BTC-USDT spot and BTC-USDT-SWAP perpetual, with native timestamps. | Production collector upgraded to same-instrument 5000-depth, with strict validation and fallback to 400-level `books`. At the verified check, **spot ±1% was fully covered** (1.049% bid, 1.4272% ask); perpetual was NOT (0.8411% bid, 0.994% ask). Never extend beyond actual native level-5000 boundary. |
| Bitget spot/perpetual BTCUSDT | Official public V3 REST 1,000-level maximum | Keep observed native levels; non-RPI data must not silently merge with RPI book |
| Gate BTC_USDT perpetual | REST documented and probed limit **300**, with native book ID and timestamp. Independently discovered public native WS V2 `futures.obu` initial **400/400** full snapshot, validated live on 2026-11-02 21:22 UTC (book ID 129812445922, bid reach 0.2832%, ask reach 0.2848%). | Production collector now prefers **400-level official Gate WS V2** and strictly falls back to verified REST 300 if unavailable or malformed; no source mixing. The Gate ±0.2% band is verified in that run, ±1% is incomplete. |
| Binance spot and Coinbase BTCUSD spot | Existing public native snapshots (up to 5,000 and full Coinbase level-2 observations, respectively) | Genuine book coverage only, with venue, currency and freshness shown |
| Gate BTCUSDT spot | Existing public book up to 1,000 levels | Missing 1% outer band remains null |

Official source references:

- Bybit new [full REST](https://bybit-exchange.github.io/docs/v5/market/full-ob), [standard public WebSocket](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook), [full WS synchronization](https://bybit-exchange.github.io/docs/v5/websocket/public/full-ob).
- [Binance USD-M depth WS API](https://developers.binance.com/en/docs/derivatives/usds-margined-futures/market-data/websocket-api), [Bitget V3 REST](https://www.bitget.com/docs/catalog/market/market-data), [OKX full orderbook 5000 API](https://www.okx.com/docs-v5/en/#order-book-trading), [Gate Futures REST API](https://www.gate.com/docs/developers/apiv4/en/futures/), [Gate native 400-level WebSocket V2 orderbook](https://www.gate.com/docs/developers/futures/ws/en/#order-book-v2-api).
- Real one-time probe, with HTTP codes, native book-id, timestamp, levels and bid/ask reach:
  [`btc-liquidity/data/deep_book_probe.json`](../btc-liquidity/data/deep_book_probe.json).
- Actual live collector and independent market probe:
  [`btc-liquidity/data/latest.json`](../btc-liquidity/data/latest.json),
  [`btc-liquidity/data/live_probe.json`](../btc-liquidity/data/live_probe.json).

**Do not bypass regional restrictions by an unauthorised mirror/proxy or call a third-party book a direct native Bybit/Binance observation.** The Bybit official WebSocket remains a verified and valuable narrower source.

## Three lagging original on-chain cost basis measurements

Original `btc-onchain/data/latest.json` source **BGeometrics**:
`realized_price`, `sth_realized_price`, `lth_realized_price`.
At the original verified audit on 2026-11-02, all three were dated **2026-10-26**,
even though other BGeometrics indicators were dated 2026-11-01. This is a
provider publication delay, not a licence to relabel an old observation as fresh.
The free daily collector preserves source dates and uses a bounded existing
request budget; repeats on the same endpoint cannot create newer underlying measurements.

**Distinct usable independent source already exists:** Bitview `realized_price_bitview`,
`sth_realized_price_150d`, `lth_realized_price_150d` with verified observations through
2026-11-01 at the audit time. Bitview's UTXO **150-day** classification is NOT
BGeometrics / Glassnode **155-day** entity-weighted classification. Keep both
sources **separate**, neither invent vendor values nor replace original series in place.
The source coverage receipt counts independent alternatives separately and
marks stale originals with `original_value=null`.

Other potential public data providers may require registration, personal API keys
and/or separate publication terms and may use another UTXO methodology. Free
availability alone is not proof of an identical, independently verified series.

## Historical L2 responsibility and actual limits

The existing **separate active automation** `Дозагрузка истории BTC L2`
remains the only owner of historic backfilling. This item did not stop, change
its schedule, recreate it, run Codex or duplicate its backfill requests.

The CryptoHFTData 11–13 UTC checkpoints and Bybit independent native 00 UTC
daily snapshots are separate kinds of historic evidence. Some source hours lack
provable full-book anchors; their absences are correctly tracked and are NOT zero
liquidity or proof of absent trades. Current LIVE depth snapshots are not
continuous L2 history, and narrow 0.01% snapshots are not complete 1% books.

## Verifiable completion criterion

1. Every selected LIVE market is either explicitly verified or rejected; exact
   bid/ask completeness reported for each 0.01/0.05/0.2/1% band (never 0 for unknown).
2. No new REST provider is silently assumed to work: actual origin-specific
   GitHub-runner probe is required and permanent geographical 403 responses are
   classified rather than endlessly retried.
3. The native Gate market uses **400 public WebSocket V2** levels when it produces a verified full initial snapshot; strict REST 300 fallback remains for WS failures. A real successful production run must record 400 native levels, both sides, exchange ID and source timestamp. The **REST-only maximum remains 300**.
4. All three lagging original onchain measurements have their actual native
   dates and non-usable status; three **separately named** independent Bitview
   alternative measurements are available where individually verified.
5. Every scheduled successful BTC bridge run regenerates `coverage_latest.json`
   and `brief.json`; integrated strict regression tests and
   `metric_quality_acceptance.json` pass with actual data.
6. Hourly ChatGPT risk automation knows that 11 working venues is not complete
   1% depth, and uses the source-capability receipt **only as a quality gate**,
   not a reason to send a routine notification.
7. Source-discovery is not complete based on narrow REST depths alone: native deeper public endpoints like OKX `books-full` must be checked for every venue. The actual verified 2026-11-02 21:28 UTC snapshot of OKX proves why treating 400 as the highest free limit was incorrect. All counts must be recomputed from continuously published genuine snapshots.

At 2026-11-02 21:22 UTC the real collector published a successful Gate **400/400** native WebSocket V2 snapshot with no collector errors and all **11/11** named markets present. The independently verified fallback is covered by unit tests. Note that 400 levels still do not guarantee 1% completeness.

These conditions allow **closing tested source capability and safe-integration work for the current named markets**, not claiming exhaustive worldwide markets, complete free 1% book depth
or removal of genuine provider publication lag.
