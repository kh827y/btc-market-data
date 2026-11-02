# BTC monitoring source bridge — item 7/8

This repository's original "Новости и риски BTC" ChatGPT automation remains hourly at UTC :34 with original news fact-checking, anti-spam and risk-signal rules. The bridge is a data adapter, NOT a trading signal.

## Outputs and fallback

- data/brief.json: first-priority compact feed, with provenance, source ages, current risk-data availability and key lookbacks.
- data/latest.json: full audited feed, all seven source paths, status for each source, missing windows, detailed metrics and per-feed warnings.
- build_feed.py: stdlib-only integration of seven committed JSON files. Stale originals remain stale despite freshly built reports.
- tests/test_bridge.py: tests for stale/future measurements, incomplete spot CVD, truncated order-book levels, and unavailable onchain records.

Nine source feeds: Binance spot price/closed UTC technicals, macro/FRED/US spot BTC ETF flows, spot-CVD, derivatives (OI/funding/liquidations/CME/COT/basis), options (Deribit and Derivasys/DVOL), onchain holders and whale indicators, current live REST order books, historical CryptoHFTData order books, and independent native Bybit historical order books.

The GitHub Actions workflow at UTC :30 also triggers after successful upstream collection jobs (seven named workflows). GitHub cron can be delayed. The bridge is published from a freshly fetched main branch, after test verification and with git push-conflict retries.

## Data use

- Source-generation age does NOT prove underlying measurement recency. Per-venue observations and onchain metric dates must be checked individually.
- Spot executed-taker flow (CVD) is NOT the same as resting bids and asks.
- A 24h/7d/30d CVD figure is null until a complete observed window.
- Historical Bybit 00:00 UTC snapshots and CryptoHFTData 11–13 UTC checkpoints are never merged or compared as equivalent daily observations.
- Separate spot and perpetual, venue, price band, timing and quote units. Missing reach or missing data is null, NOT zero.
- Changes in correlated indicators are not independent confirmations; no notification if no new material risk/event.

The ChatGPT task tries the brief via GitHub connector first, then detailed JSON, then individual original files and independent public provider sites from its existing prompt. It must switch sources after at most two failed attempts per method, rather than retrying a failed URL indefinitely.

Initial real CI verification: https://github.com/kh827y/btc-market-data/actions/runs/41409039003 . The feed had seven successfully parsed sources and flagged stale spot-CVD, excluding stale CVD figures and incomplete 24h windows from the compact current report. A successful GitHub workflow and manual connector read do NOT guarantee that an independent scheduled ChatGPT automation has actually read its JSON: verify that separately in a subsequent run.

### Spot CVD outage fix (2026-11-02)

The previous BTC spot CVD job occasionally lost its checkpoint at `git push` when another collector wrote `main` at the same time. The CVD workflow now fetches/reset-to-main, recomputes from the latest checkpoint, then retries the push (up to four attempts) rather than losing progress. It still runs on its original cron and now has independent `workflow_run` triggers from four other collection jobs; it explicitly does **not** trigger on this bridge to avoid feedback loops.

The CVD archive collector previously backfilled the oldest missing hourly files before recent 24h files, leaving the most decision-relevant 24h windows incomplete. It now processes missing hours newest-first. The output preserves strict five-venue complete windows (`net=null` unless 5/5 fully observed) and additionally publishes `complete_venue_subset` only when at least three individually fully observed venues cover the EXACT requested window. The subset has its own venue list, UTC window, and scope, and can never be claimed to represent full global BTC flow. Coinbase's historical REST pagination will need further real runs to finish older hours; a missing Coinbase hour is NOT zero. After source backfill, the bridge may show a scoped 24h signal while 5/5 complete remains false.

Additional Coinbase correction: the free Coinbase REST trade endpoint is cursor-paginated and does not yet have a CryptoHFTData backfill alternative (the provider lists Coinbase as in development). The CVD worker now performs a separate bounded newest-hours refresh in addition to continuing its persistent deep-history cursor. Thus the most recent Coinbase observations no longer disappear while the historical 24h/30d backfill continues; no incomplete Coinbase hour is guessed as zero. Historical pagination remains free but may need multiple successful scheduled runs to cover a full 24h/7d/30d window.

## Quality fixes verified November 2, 2026

The BTC price bridge uses the actual daily candle **close** (the calendar day after its UTC opening timestamp) and the latest completed weekly candle. A delayed collector does not invalidate a fully verified closed candle. The intraday Binance ticker is independently capped at 2.5h and becomes null when stale. The hourly price collector has an official Binance spot host fallback and an additional workflow-run trigger; Coinbase daily close is a separate independent cross-check. The macro/ETF bridge similarly validates component-specific publication dates and does not discard usable Fed/ETF observations solely because the collector's JSON is several hours old. An unfinished ICE DXY quote expires independently after 2.5h. Tested against real GitHub Actions results.

CVD last_complete_hour labels a UTC-hour **start**, so its observation age is measured from the end of that hour. Historical HFT noon and native Bybit midnight L2 observation times are dated snapshots, not live order-book freshness. The live order-book readiness flags now require an actually complete price band, with usable spot and perpetual venue counts separately. Source collector errors remain flagged even when valid venues are available.

The separate scheduled task **«Дозагрузка истории BTC L2»** is intentionally left in place: this feed bridge does not duplicate, halt, or reinterpret that task's running backfill as completed history.
