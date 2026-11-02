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
