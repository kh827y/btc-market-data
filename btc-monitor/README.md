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

## Autonomous collector watchdog

Implemented in `btc-monitor/watchdog.py`, deployed by `.github/workflows/btc-collector-watchdog.yml`, scheduled at UTC :03, :18, :33, :48 plus a one-way successful monitor-bridge `workflow_run` trigger. It **does not change** the hourly ChatGPT task schedule or the separate active ChatGPT task `Дозагрузка истории BTC L2`.

The watchdog independently checks **14 actual data sources/workflows** (price, spot executed CVD, derivatives, options, macro/ETF, live books, four upstream daily onchain collectors, consolidated onchain, validated monitor bridge, historical CryptoHFTData and Bybit L2 snapshots). It evaluates native `generated_utc` and measurement timestamps, respects daily/weekly bars and official reporting lags, and inspects actual GitHub workflow runs. A `skipped` or `cancelled` GitHub workflow_run is *not* evidence of successful collection; a newly published JSON is *not* proof the underlying observation is new.

On a real missing/stale critical feed, it dispatches the **specific existing GitHub workflow**, avoiding duplicate runs when one is already active. It sends at most two repair dispatches per check, waits at least two hours between attempts on a source, and caps each source at three per 24 hours. Failed or unauthorized dispatches are separately recorded. Historical L2 is observed **without** triggering a competing backfill, because the existing external `Дозагрузка истории BTC L2` task handles that. Data completeness gaps (e.g. Coinbase 24h not complete or vendor-delayed onchain) do *not* cause endless replays of otherwise healthy collectors.

Published receipts:
- `btc-monitor/data/health_latest.json` — status, checked UTC, workflow API access, actual source statuses, recovery decisions, named missing coverage.
- `btc-monitor/data/watchdog_state.json` — prior confirmed successes and cooldown/dispatch timestamps.
- `btc-monitor/data/watchdog_recovery_test.json` — one-shot real recovery-path verification: a **simulated missing observation** successfully triggered an actual `workflow_dispatch` to the existing BTC macro collector, and GitHub ran that collector successfully, without changing live BTC market data to manufacture a failure. Actual test run: https://github.com/kh827y/btc-market-data/actions/runs/41515168535 .

The monitor's `brief.json` embeds a dated compact `collector_watchdog` section. The actual ChatGPT automation independently reads the original `health_latest.json` and **does not trust a stale watchdog**. If the entire GitHub Actions service is disabled, an Actions-based watchdog cannot repair itself; the independent hourly ChatGPT monitor can detect the old heartbeat and use its existing one-time critical-data-warning policy. There is no claim of 100% reliability, permanent API access, or complete global market coverage.

Verification criterion: actual source/date integrity; successful code and real GitHub workflow runs; one authenticated real workflow dispatch and successful downstream run; persisted health receipt; integration in real hourly monitoring prompt. Long-running reliability still requires operational observation over time and retains truthful per-feed status.

## Item 4: per-metric BTC data quality

The source-level validated bridge is supplemented by an **independent per-metric audit** in `btc-monitor/metric_quality.py`. The two operate as an AND gate, **never** as an OR gate: a source wrapper must be `sources.<family>.status=fresh`, and a particular `metric_quality.checks.<metric>.status=usable` before it is eligible as current evidence of a BTC trend change. The validator explicitly flags `stale`, `incomplete`, `invalid`, `unverified`, `unavailable` and `not_comparable`; no failed measurement becomes zero.

Rules enforced and independently tested:
- Binance BTCUSDT spot price uses closed UTC daily/weekly bars and a separately dated live spot quote; weekly MA200 never derives from an unfinished candle.
- **Executed spot CVD:** original five Binance/Coinbase/OKX/Bybit/Kraken versus a separate Binance/OKX/Bybit/Kraken/Bitget fixed set; dynamic subset explicitly lists its changing venues. For 1h/24h/168h/720h the source UTC window, per-venue exact `required` and `hours`, trade-ID continuity proof (Coinbase 24h/7d/30d), venue count, native quote scope and arithmetic sum must match. A failing or incompletely observed original-five window sets `net_usd_approx=null` and `complete=false`.
- **Derivatives:** five named OI venues must add up to the exact normalized USD notional and have a dated observation; settled funding compares the **actual normalized 8h rate** (not raw estimates); reported Binance+Bybit long/short liquidation totals must reconcile; weekly CFTC CME futures positions retain the Tuesday observation date and 5 BTC contract unit; dated non-CME basis requires all four legs with **identical maturity**, and CME basis needs its own contract, spot match, and expiry.
- **Options:** Deribit approximate mark 25Δ RR must equal call IV minus put IV in **volatility points**, not rates; each term has verified expiry brackets and its own timestamp. Distinct 30d DVOL and daily Derivasys published research remain separately dated.
- **Onchain:** source-method and UTXO cohort remain explicit; independent Bitview 150-day cohorts are NOT the same as 155-day entity-based ones. Dated upstream `delayed/error/stale`, missing values and missing source freshness prevent numeric use; honest missing data stay null. Corrections and vendor lag do not imply Bitcoin has no risk.
- **Macro/ETF:** individually dated observed US yields, rates, DXY versus trade-weighted broad USD, and 1/5/21 published sessions of actual US spot Bitcoin ETF creations/redemptions. Five ETF session dates must be distinct, descending and match the latest session.
- **LIVE depth:** each of 11 named venues/instruments, native source timestamp for WS, actual bid AND ask coverage, and separately observed 0.01/0.05/0.2/1% bands. Partial band values are *unknown*, never forced to zero. A fresh file does not prove that a failed individual Bybit/Binance market is usable.
- **Historical L2:** source's actual snapshot date, clock (Bybit 00 UTC versus CryptoHFTData 12 UTC), same venue/instrument/level-band, baseline date and lookback interval required for comparable percentages. A single-point historical snapshot is not continuous LIVE depth.

Outputs: full `metric_quality.checks` audit, statuses, scope/units, observed times, stable `comparison_key` identifiers (not including observation timestamp) and explicit reasons in `btc-monitor/data/latest.json`; the compact downstream `btc-monitor/data/brief.json` includes the same individual checks and family readiness. Invalid direct values are masked to null in the compact signal payload rather than only accompanied by warnings. Source-independent watchdog health is a different axis and cannot upgrade unavailable market metrics.

Verification: `btc-monitor/tests/test_metric_quality.py` contains adversarial bad-source cases (forged complete CVD, missing time, invalid RR sign, stale Onchain, wrong source time/level, wrong 00/12 UTC L2 comparison, unbalanced OI and independent macro identities). Existing bridge tests cover integrated brief and family gating. Actual GitHub CI runs `python -m py_compile` plus the entire monitor regression suite on every code/prompt change; sampled real status can be inspected in `brief.json.metric_quality`. This verifies the *code path and available observations*, not perfect external coverage or correctness of an upstream vendor's economic data.

The scheduled task `Новости и риски BTC` requires both parent `sources.*.status=fresh` and individual `metric_quality.checks.*.status=usable`; an expired, absent or contested audit means independently verifying the source rather than inventing a signal. No generic technical-status notification is sent merely because a source was repaired. The separate automation `Дозагрузка истории BTC L2` is unchanged.
