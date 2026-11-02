# BTC monitoring source bridge — item 7/8

This repository's original "Новости и риски BTC" ChatGPT automation remains hourly at UTC :34 with original news fact-checking, anti-spam and risk-signal rules. The bridge is a data adapter, NOT a trading signal.

## Outputs and fallback

- data/brief.json: first-priority compact feed, with provenance, source ages, current risk-data availability and key lookbacks.
- data/latest.json: full audited feed, all seven source paths, status for each source, missing windows, detailed metrics and per-feed warnings.
- build_feed.py: stdlib-only integration of seven committed JSON files. Stale originals remain stale despite freshly built reports.
- tests/test_bridge.py: tests for stale/future measurements, incomplete spot CVD, truncated order-book levels, and unavailable onchain records.

Seven input categories: spot-CVD, derivatives (OI/funding/liquidations/CME/COT/basis), options (Deribit and Derivasys/DVOL), onchain holders and whale indicators, current live REST order books, historical CryptoHFTData order books, and independent native Bybit historical order books.

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
