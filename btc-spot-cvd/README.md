# BTC executed spot CVD — actual trade history (free sources)

Collector: `collector.py`. Scheduled workflow: `.github/workflows/btc-spot-cvd.yml`.
Outputs: `data/latest.json` and checkpoint `data/state.json`.

## Sources and instruments

* Binance spot BTCUSDT; OKX spot BTC-USDT; Bybit spot BTCUSDT; Kraken spot BTC_USD; Bitget spot BTCUSDT — hourly trade Parquet from CryptoHFTData's public REST free tier (max 60 calls/min by IP). Source uses `received_time` UTC-hour partition and `is_buyer_maker`: maker-buyer means sell taker. The collector uses explicit verified spot symbols, not the futures symbols.
* Coinbase Exchange spot BTC-USD — public REST trade-id pagination; Coinbase's `side` indicates maker side, and is inverted for taker flow. Closed hour is counted only after scanning into an older hour. Persistent historical cursor and separate recent refresh keep new intervals from disappearing during deep backfill. Coinbase's paid trade archives are NOT required or used.

## Windows and strict coverage

Every `windows[1h,24h,168h,720h]` is calculated from the **same completed UTC hours** (approximately two hours behind wall clock), using dollar/USDT quote notional at executed prices. Missing hours are null, NOT zero.

* `complete` and `net`: **original fixed five** (Binance, Coinbase, OKX, Bybit, Kraken) only. If any missing hour on any of those five, `complete=false`, `net=null`.
* `fixed_five_ex_coinbase`: **different fixed five** (Binance, OKX, Bybit, Kraken, Bitget), with their own `complete`/`net`, never a substitute for Coinbase's own market flow. Valid only if all five markets fully cover every UTC hour of requested window.
* `complete_venue_subset`: only individually complete observed venues among the six currently monitored. Scope and venue list MUST be displayed. It can vary over time and must not be compared as one fixed index unless its composition is identical.

These aren't worldwide market totals. USDT is treated as approximately USD, not exact during depegs. Trade flow is executed taker demand, NOT order-book depth, exchange deposit flow, or evidence of institutional buying. The 1h/24h/7d/30d totals are overlapping windows, not independent confirmations.

## Backfill

The collector prioritizes most recent missing archive hours, then fills older hours, uses provider rate-limit pacing and saves failed UTC hour attempts with a bounded retry cooldown. Coinbase pagination is bounded per run, preserving state and independently refreshing recent closed hours. Backfill may take multiple actual successful GitHub Actions executions. Do **not** claim complete 7- or 30-day CVD until `complete=true` in the latest output and the market-data bridge confirms fresh source timestamps. The workflow's success alone is insufficient.

## Quality checks

Collector unit tests test original-five vs alternate-five scope, no zero substitute for missing Coinbase, continuity and retry behavior. Bridge unit tests reject unverified alternate venue sets and do not mark an incomplete original five as complete. Downstream hourly BTC monitoring reads the repository's `btc-monitor/data/brief.json` and falls back to source JSON if freshness or integrity isn't satisfactory.

## Verified original-five 720h Coinbase restoration — 2026-11-02

The historical **Coinbase Exchange BTC-USD** original-five missing venue was fully recovered using **only Coinbase's official free REST /products/BTC-USD/trades API**. A direct probe confirmed that `limit=1000` yields 1,000 sequential trade IDs per page, and `after=<trade_id>` permits read-only random access to historical trades without scanning the entire tape from today. Source side is the **maker** order side and must be inverted for taker buy/sell CVD.

`coinbase_parallel_backfill.py` (manual Actions workflow `.github/workflows/btc-coinbase-parallel-backfill.yml`) divides 720 completed UTC hours into **12 nonoverlapping 60h shards**. Each shard searches for its exact upper UTC boundary by trade ID, scans all descending 1,000-execution pages, rejects missing/duplicated IDs and nonmonotone timestamps, and certifies both boundaries with actual trades. Shards and their cross-boundary trade IDs are independently validated before merging against the latest canonical repository state; no gaps, zeros, OHLC volume proxies, or paid data are substituted.

Real GitHub Actions run: https://github.com/kh827y/btc-market-data/actions/runs/41517250949 . Verified anchor: **2026-11-02 18:00 UTC**, all **720/720 Coinbase hours**, 12 successful shards, **12,035** actual trade pages / approximately **12.035 million** scanned executions. The merged original-five CVD `windows[24h/168h/720h].complete` was **true for all three**. Previously saved hour totals had **zero material disagreements**. Audit file `btc-spot-cvd/data/coinbase_full_backfill_status.json`; new hourly integrity fields in `btc-spot-cvd/data/latest.json` and `btc-monitor/data/brief.json`.

**Ongoing freshness:** `btc-spot-cvd/coinbase_recent_repair.py` runs during the normal CVD collector; it identifies missing newly closed recent Coinbase UTC hours, seeks directly to each missing interval's upper boundary, scans every contiguous public trade, and commits an hour only after both UTC bounds have been crossed. Runs are bounded (default 250 pages for 30 recent hours), and the CVD summary explicitly exposes any remaining gaps rather than claiming completeness. When the last 720 hours already exist, the expensive deep-history cursor is not re-run. The existing hourly watchdog checks availability of the newest complete original-five **1h** executed-trades window and can restart the CVD collector if needed.

A second, **real** independent GitHub-runner integration test deleted one already verified hour only from an **in-memory copy** and fetched it anew from Coinbase official REST: 2026-11-02 18:00 UTC, 20,227 actual trades, 21 pages, matching the independent backfill's trade count and USD buy/sell/net to within $0.02. Receipt: `btc-spot-cvd/data/coinbase_recent_repair_test.json`.

**Important time-basis limitation:** Coinbase native REST is grouped by actual exchange **trade timestamp**, while CryptoHFTData's other spot exchanges are partitioned by collector **received timestamp**. They are near-equivalent for broad 24h/7d/30d comparisons but not literally identical at UTC hour boundaries. These are **selected five** spot venues, not the global BTC spot market; USD and USDT are approximately but not exactly the same denomination. Coinbase window integrity is evaluated independently of other venue completeness; if a future source has a gap, the five-venue aggregate becomes null, never zero.

The separate ChatGPT automation `Дозагрузка истории BTC L2` remains active and unchanged. Coinbase executed trades and historical Level 2 order-book snapshots are different data products and have separate workflows.
