# Historical BTC L2 audit — 2026-11-02 UTC

## Data integrity contract

Historical L2 metrics are **point-in-time visible orders**, not trades,
daily medians, realized buys, or continuous order-book history. Never combine
spot and perpetual markets, dissimilar venue sets, timestamps, or percent
bands. A band is usable only if both bid and ask reach that band. Null means
unmeasured, **not zero**. USDT values are USD approximations.

## Independent official-public Bybit ZIP archive

* Native daily BTCUSDT order-book archive: quote-saver.bycsi.com, original
  source dates 2023-01-18 through 2026-11-01 for linear, 2025-04-29 through
  2026-11-01 for spot (eligible 1384 + 552 days as of this audit).
* 12 parallel date-shard workers; merge enforces exact source-day accounting.
  Before 2026-11-02 millisecond-clock fix: linear 1350/1384 (34 errors);
  spot 551/552 (1 error). Last seven and 30 source dates were all verified.
* Root cause of **32** linear errors: original first snapshot at
  23:59:59.997–23:59:59.999 UTC, just 1–3 milliseconds before the file's
  declared calendar midnight. bybit_independent.measure now allows at most
  10 ms negative skew and retains the actual timestamp; the merge validates
  the same tolerance. This is not a license to accept earlier-day snapshots.
* Three observed substantial genuine archive gaps are **not fixed by clock
  tolerance**: linear 2023-01-18 starts 06:42:57 UTC; linear 2025-08-21
  starts 02:14:17 UTC; spot 2025-04-29 starts 02:59:33 UTC. These are not
  midnight snapshots and remain explicit errors until independently
  verified from another authentic original source.
* **Expected, not yet claimed as achieved:** after fresh 12-shard backfill
  and verified merge, linear 1382/1384, spot 551/552. Re-read the actual
  published data/bybit_full_backfill_status.json and require
  verified + explicit_error = eligible with no unaccounted days.
* A range request inflates only the first real snapshot in a ZIP. The full
  archive's CRC is **not** verified; source depth is 200/500 levels and
  outer price bands can remain null.

## CryptoHFTData seven-market hourly archive

* Archive begins 2025-06-28, at least 492 eligible dates as of 2026-11-01.
  Seven distinct BTC spot/perpetual markets, primarily 12:00 UTC checkpoint,
  with 11:00/13:00 candidate hours. The official source explicitly warns
  that some hourly files have no trustworthy snapshot and may contain only
  incremental updates.
* As published before the strict audit correction, hft_latest.json
  reported 34–36 observed dates per venue, including 7/7 and 30/30 recent
  dates. **These totals were overoptimistic** because some old records
  labeled "hour-start checkpoint" had no native event_type=snapshot
  provenance. Such legacy records are now excluded from coverage and
  scheduled for actual snapshot revalidation. Do not quote old 100%
  7d/30d coverage as proven until a fresh strict audit is published.
* The parser requires genuine snapshot rows and bid/ask integrity; it never
  fills a missing book from zero or replays unanchored deltas as if full.
  Missing 11/12/13h native checkpoints are explicit failed hours, not zero
  liquidity. New source_date_audit distinguishes source dates verified,
  fully attempted but unverified, and not yet fully checked.
* Run the existing twice-hourly GitHub Action; 90 downloaded files per run
  with HTTP pacing and 429 backoff, recent dates first. Do not disable
  collection because a single older date lacks snapshots; continue through
  available dates. Missing checkpoint hours are retried after 7 days in case
  the vendor republishes the archive.
* Strict same venue/instrument/clock-time/percent-band matching is required
  for 1d/7d/30d/90d/365d comparisons. Do not call incomplete 365d coverage
  a historical 365d median.

## Exit criteria for the separate backfill automation

1. Confirm fresh Bybit merge for both markets with every eligible original
   date accounted for, and only genuine midnight-source gaps remaining.
2. Confirm HFT latest from the strict verifier; all seven venues' real
   7d/30d coverage must be reported accurately, including honest partial
   coverage and irreducible snapshot gaps.
3. Continue improving HFT free historical coverage until the source is
   exhausted or all source dates are attempted/explicitly excluded; do not
   pretend 100% global history when native snapshots are absent.
4. Only after verified completion, notify once, disable **only**
   auxiliary automation 6ae85921e2d8819192102b06b216b141.
   Do not alter the main BTC monitor or other auxiliary tasks.

Sources: official Bybit quote-saver daily ZIP archive; CryptoHFTData
order-book dataset and its "No snapshot in your order book file?" technical
article; the published GitHub JSON status files and native parser unit tests.
