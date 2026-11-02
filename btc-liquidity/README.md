# BTC visible order-book depth — plan item 6/8

Automatic hourly collection without API keys or paid services of BTC spot and perpetual order books. GitHub Actions runs at UTC minute 19, ahead of the risk monitor at minute 34.

## Live sources and quality

Spot markets: Binance BTC/USDT, Coinbase BTC/USD, Bybit BTC/USDT, OKX BTC/USDT. Perpetual markets: Binance, Bybit and OKX BTCUSDT. Data are **venue-local quotes**, not a worldwide BTC book. Each observed snapshot records time, best bid/ask midpoint, spread, level count, observed book reach, visible bid and ask notional within 0.05%, 0.2% and 1% of midpoint, and bid share.

Bands beyond actually observed depth are **null, never zero**. Missing API, stale timestamps, abnormal spreads, crossed/unordered books and price outliers are quarantined. A resting visible order can be cancelled, so visible depth is NOT executed trades, guaranteed support, or liquidation-price density.

For OKX perpetuals, contract counts are converted into BTC using the current public instrument ctVal and ctMult (BTC-denominated contracts only), and are rejected if denomination changes. Like-for-like changes over 24 hours, 7 days and 30 days are calculated ONLY when a genuine earlier snapshot exists, within +/-3 hours of target time, for the same venue/instrument/band. The raw hourly sampled history is retained ~32 days; the history genuinely begins when the GitHub workflow runs. There is no invented or reconstructed older spot orderbook.

## Archived futures: independent older historical series

Binance public USD-M perpetual bookDepth 30-second archival samples are used for 2026-06-01 to 2026-09-02 ONLY. A background backfill processes up to 100 daily ZIPs per run (450-second limit; resumes if incomplete), validates archive rows, and derives daily medians of bid/ask USD notional at 0.2%, 1% and 2% bands. Historical perpetual prices must not be mixed with spot liquidity and are not a substitute for modern spot-depth data.

**Known upstream defect**: Binance futures archival ask depth froze in several inner bands from 2026-09-03. See https://github.com/binance/binance-public-data/issues/496 . Newer archived dates are excluded; a valid ZIP checksum does not imply valid underlying observations.

## Outputs

- btc-liquidity/data/latest.json — machine-readable current snapshot, venue coverage, comparable history only where it exists, source timestamps, quality status, and errors.
- btc-liquidity/data/history.json — retained live snapshots, backfilled historical Binance futures daily aggregates, per-day failures. Data files will be created by the first successful workflow run.

The scheduled monitoring automation must verify generated_at and status, check book reach for every band, and treat this as additional market context, NOT a stand-alone reversal signal. The monitor reading this JSON is **not** automatically guaranteed until item 7/8 (integration) is completed.

Limits: Source APIs can block GitHub runner IPs; errors stay visible. 1h REST snapshots miss brief liquidity events. The quote is USDT on most venues and is treated as approximately USD for large-scale research (not exact execution cost). A free multi-year multi-venue spot Level 2 archive is not claimed.


## Full free source backfill (additional historical layer)

A separate verified historical L2 collector now reads free [CryptoHFTData](https://www.cryptohftdata.com/docs/rest-orderbook) hourly Parquet files from the published archive since 2025-06-28. Public GET /download requires no key (60 requests/minute free). A genuine daily checkpoint in the 11:00, 12:00 or 13:00 UTC hourly file is extracted (12:00 preferred) for **Binance Spot, Bybit Spot, Bitget Spot, OKX Spot, Binance USD-M Futures, Bybit linear perpetuals, and OKX USDT perpetuals**. Only genuine vendor snapshot rows are used, including checkpoints that occur later within the selected hour. If the preferred hour lacks a verifiable snapshot, it attempts neighboring 11:00 and 13:00 UTC files, never extrapolating unanchored updates as full depth. It excludes malformed/non-Parquet responses, crossed books and incomplete price-band reach. Historical quantities on OKX USDT perpetuals assume 0.01 BTC/contract: check historical contract changes before relying on distant dates.

* btc-liquidity/data/hft_latest.json — source-qualified daily 12:00 UTC historical book-depth snapshots by exchange, 1/7/30/90/365-day like-for-like date comparisons (only when observation clock times differ by at most 2 hours) and 7/30/90/365-day observed baselines **only after enough distinct valid days exist**.
* btc-liquidity/data/hft_history.json — actual 12:00 snapshots with source path, date, instrument type, levels, spread, 0.01%/0.05%/0.2%/1% reach, bid/ask USD notional and validation errors. It does not publish the raw provider dataset or pretend that one checkpoint is continuous L2 coverage. The original 2026-06 to 09 pre-defect Binance futures bookDepth records remain a separate type of archive.

GitHub Actions [btc-hft-l2.yml](../.github/workflows/btc-hft-l2.yml) runs on every hour at UTC :23, fills a bounded batch from the entire available publication history beginning 2025-06-28, prioritizes comparators before sequential backfill, and rechecks missing source checkpoints after 7 days, and continues over subsequent runs. There is no payment or Codex. Historical completeness is reported per venue and never assumed if an old file is absent or lacks a starting snapshot. Read the provider's [documented gaps and corrections](https://www.cryptohftdata.com/docs/data-gaps-and-corrections) before declaring a long-term statistical conclusion.

**Important:** archive backfilling does not automatically update the ChatGPT risk-monitor automation's prompt. The next integration item needs to read and verify freshness and quality of BOTH hft_latest.json and latest.json. Unlike our current live REST sampled books, daily source checkpoints can provide reliable backdated anchors for like-for-like historical comparisons.

### Item 6 verified-data policy

Missing exchange snapshots remain a **real completeness limitation**, not a reason to fabricate depth. Provider documentation explicitly says an old hourly file can contain only changes but no anchor. We do not call an unanchored reconstruction a 'verified full order book'. The collector tries three nearby hourly files and transparently records unresolved gaps for future rechecks. Real source time, complete band coverage, observation method and UTC-hour offset are retained in each comparison. The shallow 50-level Bybit spot/perpetual snapshots support a **separate 0.01% band**, while their 0.05% or wider bands frequently remain null. Never compare a Bybit 0.01% depth number to a different venue's 0.05% number as if they measured the same distance. Seven markets do not equal worldwide liquidity. A historical daily point-in-time snapshot cannot detect short-lived intraday liquidity withdrawal; live REST and other monitoring metrics are needed for that use.

The QA target is to obtain useful same-clock 1/7/30-day comparisons, defensible longer comparisons where snapshots exist, and a reproducible coverage report. Do not call the older multi-year series exhaustive until its actual per-exchange coverage supports that claim.

Quality detail: the collector groups Binance split REST snapshots by their native event time and last update ID (not reception timestamp), and ignores byte-identical duplicate levels while rejecting conflicting duplicates. Source: https://www.cryptohftdata.com/blog/missing-orderbook-snapshots . Old files with only unanchored updates remain excluded from *certified complete depth* until the provider supplies a verified anchor; the separate source documents rapid near-mid reconstruction but warns that distant dormant orders can remain invisible.


## Independent free Bybit historical L2 since 2023 (verified 2026-11-02)

**A separate Bybit-hosted archive, not CryptoHFTData:**
- BTCUSDT perpetual: https://quote-saver.bycsi.com/orderbook/linear/BTCUSDT/ (listing from 2023-01-18). The source has 500 levels through 2025-08-20 and 200 thereafter.
- BTCUSDT spot: https://quote-saver.bycsi.com/orderbook/spot/BTCUSDT/ (listing from 2025-04-29; 200 levels).
- The independent collector at btc-liquidity/bybit_independent.py uses free HTTP byte-range requests for **only the first 512KiB** of each large daily ZIP and expands the beginning of the native DEFLATE file. It validates the first genuine snapshot, price ordering, quote sizes, source u/seq IDs, date, capture time within 180s after midnight UTC, and actual level reach. Partial extraction **cannot validate the CRC of the entire ZIP**. This is disclosed in each record. The extracted initial depth is a real midnight instantaneous book, not a daily mean or continuous record.
- Only complete observed bid/ask depth inside 0.01%, 0.05%, 0.2% and 1% bands is emitted; insufficient band reach is null. Comparisons are at the same market, same band and UTC clock for 1,7,30,90,180,365,730,1095 days only when validated source observations exist.
- Machine-readable outputs: btc-liquidity/data/bybit_independent_latest.json (current source coverage and comparable baselines) and btc-liquidity/data/bybit_independent_history.json (genuine daily checkpoints and retryable errors). GitHub Actions btc-bybit-independent.yml runs at UTC minute 26 hourly, prioritizes dates used in lookbacks, interleaves spot and perpetual, then fills the older archive without inventing missing snapshots.
- First two real runs 2026-11-02 succeeded with **120 valid spot days and 120 valid perpetual days**, 240 observations total and zero observed errors in those batches. The perpetual archive already supports a verified comparison at 1,095-day distance for the narrow **0.01% band**. The complete multi-year daily backfill is *not yet finished*; available levels are not extrapolated into a wider global order book.

An alternative independent vendor, Tardis.dev, exposes whole-day BTC historical L2 samples on **the first day of each month** without API key. Those sparse samples are useful for cross-checking historical methodology, but **not** a substitute for free daily history: https://docs.tardis.dev/downloadable-csv-files .

For later monitoring item 7: choose live latest.json for current liquidity, hft_latest.json for multi-venue 12:00 historical context, and bybit_independent_latest.json for longer 00:00 Bybit spot/perpetual baselines. Never compare different venues, markets, clock times or band widths as identical. Never use resting limit orders as executed buying, guaranteed support, or a sole signal of reversal. The scheduled ChatGPT trend monitor is **not automatically integrated** by creating these collectors; that remains item 7.

## Live REST source recovery — November 2026

The original free GitHub runner observed Bybit Spot/Perpetual HTTP 403 and Binance USD-M Futures HTTP 451. These are **not** treated as available, and a different exchange is never mislabeled as Binance/Bybit.

The live `collector.py` now also attempts independently branded public BTC order books: Bitget BTCUSDT **SPOT**, Bitget BTCUSDT **USDT-FUTURES**, Gate BTC_USDT **SPOT**, and Gate BTC_USDT **USDT perpetual**. Spot and perpetual are kept separate by venue. The new Gate USDT perpetual order-book sizes are in **contracts** and are multiplied by the live BTC_USDT contract's `quanto_multiplier`; missing/changed metadata rejects the observation, never silently counts contracts as BTC. On the Bitget v3 order-book, quantities are treated as BTC base units for BTCUSDT. Its authenticated trading API is not used.

Shallow public books can be informative at the new `0.01%` band even when `0.05%` or `0.2%` are incomplete; complete reach is mandatory for each side and each band, and all incomplete totals stay null rather than zero. No global aggregated depth and no direct comparisons of heterogeneous venues are fabricated.

The independent workflow `.github/workflows/btc-liquidity-live-probe.yml` writes `btc-liquidity/data/live_probe.json` after real venue requests and code tests. **The presence of code or success of offline tests alone does not prove that a new venue was actually reached from GitHub Actions**; verify both the probe and latest.json, including their timestamps and reported errors.

## Item 4: accelerated *verified* historical depth backfill, 2026-11-02

Two different, non-interchangeable historical observations remain available free of charge.

1. **CryptoHFTData 11–13 UTC daily checkpoint** for seven spot/perpetual markets since 2025-06-28. The hourly parquet archive includes updates and sometimes no provable snapshot. The algorithm strictly rejects any unanchored older file; it tries neighboring 12/11/13 UTC hours and retries genuine gaps later. The rate-limited anonymous API now observes the published 60/minute limit and honors HTTP 429 `Retry-After`, and gives priority to *all 30 most recent dates* ahead of longer historical dates. `hft_latest.json` reports `recent_window_coverage[7d/30d/90d/365d]` **per market** in addition to coverage of the entire 492+ day vendor archive. An archived day counts only when a real checkpoint passed both bid/ask and band validation. Older files with unanchored updates are not falsely marked complete.
2. **Bybit native midnight BTCUSDT spot/linear first checkpoint**: separate archive hosted on `quote-saver.bycsi.com`. The existing hourly collector remains active. `btc-liquidity/bybit_parallel_backfill.py` and `.github/workflows/btc-bybit-full-backfill.yml` additionally execute a **one-shot parallel split across 12 source-date workers** (8 for the longer linear source, 4 for spot). Each worker validates ZIP header, Bybit native sequence and timestamp, price ordering, actual declared level coverage and each date, with bounded network backoff. Workflows merge verified dates only after all 12 workers have completed successfully, preserve existing valid checkpoints, reject missing/misaligned shards, and publish `btc-liquidity/data/bybit_full_backfill_status.json` with actual unavailable dates and measured coverage. The first source ZIP message is checked via HTTP range; this does not establish full ZIP CRC validation.
3. `btc-liquidity/data/historical_test_status.json` is the independently committed regression status from `.github/workflows/btc-l2-historical-tests.yml`. Unit test success does **not** prove the bulk job has completed or all historical source dates exist.
4. The ChatGPT risk-monitor bridge exposes historical `coverage_30d` separately, without confusing the % of the total archive with the % of the last month. Do not combine midnight Bybit records with 12:00 CryptoHFTData records or spot/perpetual.

**As of the initial Nov 2 review** the 7-market CryptoHFTData global archive covers 25–26 verified dates per market out of 492, but the most recent 30 days already contain roughly 24–25 valid checkpoints per venue; remaining month-end dates were still being backfilled. The Bybit native archive contains 120 verified dates *per market*, with full daily backfill pending. These numbers must be checked against the latest published output before claiming completion. Some vendor-documented historical gaps cannot be recovered by simply retrying an API; mark them as unverified and use an independent vendor when possible.

## All 11 selected LIVE BTC markets restored — November 2, 2026

The previous GitHub-runner Bybit HTTP 403 / Binance USD-M HTTP 451 failures were resolved using each exchange's **own official public mainnet WebSocket market data**, without proxies, jurisdiction-switching, testnet, or substituting a different exchange/instrument:

- **Bybit Spot BTCUSDT**: `wss://stream.bybit.com/v5/public/spot`, topic `orderbook.1000.BTCUSDT`, native **snapshot** only (not delta). Verify `s=BTCUSDT`, `u`, `seq`, exchange `ts` freshness and both sides.
- **Bybit USDT Perpetual BTCUSDT**: `wss://stream.bybit.com/v5/public/linear`, same 1000-level topic; spot and perp remain separate markets.
- **Binance USD-M Perpetual BTCUSDT**: `wss://ws-fapi.binance.com/ws-fapi/v1`, official WS API `depth` method, `symbol=BTCUSDT, limit=1000`; verify matching request id, success status, native `lastUpdateId`, `E` timestamp, bid/ask levels. A separate partial 20-level stream was tested but **not** used because it lacks reliable 0.05%/0.2% depth.

Source docs:
- https://bybit-exchange.github.io/docs/v5/ws/connect
- https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-api/market-data-requests

Implementation `btc-liquidity/official_ws.py` is used by BOTH `collector.py` and `probe_live.py` for these exact three markets. Other eight existing public REST books remain unchanged. WebSocket dependencies are installed only in the LIVE workflows, never in the separate historical L2 automation. `test_official_ws.py` tests wrong-market, wrong-symbol, delayed timestamp, partial-delta, insufficient sides, request ID and sequence verification.

**Real production evidence:** First successful live production collector reported **11/11 selected exchanges/instruments, zero source errors**, with **6/6 spot + 5/5 perpetual**. All three recovered exchanges returned genuine 1,000-by-1,000 bid/ask order-book snapshots and complete 0.01% plus some wider bands; see `btc-liquidity/data/latest.json` and `btc-liquidity/data/live_probe.json`. Independent `btc-monitor/data/health_latest.json` now validates all 11 named markets and specifically checks native Bybit/Binance WebSocket provenance and source time; missing just one real market is a recovery-worthy outage. Main `btc-monitor/data/brief.json` publishes `family_readiness.current_all_11_selected_orderbooks`, along with source timestamps, transport and individually complete bands.

**Do not overstate completeness:** Individual public API books can be limited to 100/400/1000/5000 levels; a missing 1% (or even 0.2%) band means **no full depth beyond returned levels**, not zero liquidity. Coinbase is BTCUSD; others BTCUSDT (USDT only approximately USD). WebSocket snapshots remain periodic point-in-time observations, **not** continuous multi-year Level 2 history and not guaranteed realizable orders. Any future 403, 451, stale exchange timestamp or incomplete band is disclosed, not silently replaced.

The existing separate active task **«Дозагрузка истории BTC L2»** remains responsible only for historical snapshots/backfill; these LIVE changes neither stop it nor duplicate its work.
