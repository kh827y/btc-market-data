# BTC monitor — item 6: source reliability, automated recovery and false-confidence gates

## Objective and acceptance

Complete the next necessary reliability stage **without purchasing unnecessary datasets** and without changing the separate "Дозагрузка истории BTC L2" automation. Readiness is conditional on independently validated underlying observations; a recent GitHub commit, recent JSON wrapper, or all-API-responding headline does not imply reliable trade signals.

Acceptance conditions:

1. Every essential current signal family is tracked independently and source-native timestamps distinguish stale observations from newly published JSON.
2. A fresh monitor bridge **cannot conceal** invalid/unavailable/critical current indicators from the health controller.
3. The health controller distinguishes a real repairable collector failure from degraded underlying quality: do not continuously replay a healthy bridge or blocked vendor API.
4. Real GitHub Actions workflow dispatch is tested; hourly watchdog can take bounded recovery decisions and must not dispatch the separate historical L2 automation.
5. Live feed aggregation and policy unit tests complete, and reports verify current data with no critical issues.
6. Genuinely incomplete metrics remain null, not zero. No spurious BTC trading alert is sent due solely to a data-collection or API improvement.

## Actual implemented fixes

- `btc-monitor/watchdog.py`: assess `monitor_bridge` **metric_quality.checks**, `critical_issues`, and freshness of seven essential source families. Missing quality contract is an actionable invalid schema; stale/critical upstream content is marked `degraded_critical_inputs` and reported in `degraded_input_quality_no_duplicate_recovery`, **without** repeatedly dispatching the bridge for an upstream data problem.
- `btc-monitor/watchdog.py`: validate native source time versus capture time for OKX spot+perpetual, Bitget spot+perpetual, and Gate spot+perpetual, in addition to the already checked Binance and Bybit WS snapshots. Failed native timestamps mark only their actual exchange book unverified and are actionable by the original collector, not replaced with another venue.
- `btc-monitor/metric_quality.py`: added the **same independent native timestamp gate** before a live book can become a current risk metric, and an official known-source transport allowlist. An unrelated proxy, stale exchange timestamp, or fresh wrapper with old REST data cannot confirm a current trend signal.
- Regression tests in `btc-monitor/tests/test_watchdog.py` and `btc-monitor/tests/test_metric_quality.py` cover these cases, including no duplicate bridge recovery and null-safe quarantining.
- The existing production automation prompt already requires two materially **independent** evidence groups except for a verified systemic shock, suppresses routine status reports, and distinguishes incomplete/lagged metrics. The policy's counterfactual decision scenarios are `btc-monitor/policy_test_scenarios.md`. CI validates the written policy structurally; **it does not execute or prove an LLM's future alert decisions**.

## Observed production acceptance, 2026-11-02 UTC

- `btc-monitor/data/health_latest.json` at **22:17:45 UTC**: `healthy`, 14/14 checked source controls, GitHub workflow API reachable, no stale/missing controller inputs, no queued/blocked recovery and no redundant dispatch. This confirms a real watchdog run with the tightened rules.
- `btc-monitor/data/metric_quality_acceptance.json` at **22:18:06 UTC**: `verified`, **195 checks**, **0 critical issues**, 184 usable, 8 incomplete, 3 stale. All nine underlying feed families marked fresh **as files**, with individual metric gates still controlling admissibility.
- `btc-monitor/data/policy_test_status.json` at **22:18:06 UTC**: GitHub CI bridge quality checks and versioned alert-policy structural contract passed after both fixes. It is NOT proof of platform notification delivery.
- `btc-monitor/data/watchdog_recovery_test.json`: earlier, at **20:00 UTC**, real GitHub Actions `workflow_dispatch` of the macro ETF collector succeeded and its run ID was recorded. The test simulated a stale condition rather than failing a live market source; it confirms dispatch capability, **not** end-to-end recovery from every future live outage.
- Main hourly automation "Новости и риски BTC" remains enabled. Its last independently inspected run (21:41 UTC) successfully read current source health and evaluated market risk; **it preceded these final code changes** and therefore must not be represented as a post-fix model/notification test.
- Separate historical BTC L2 backfill and its schedule unchanged.

## Material limits and priority

- **No additional source required for this stage:** reliable trend assessment has live spot and technicals, executed spot CVD, OI/funding/liquidations, options, ETF/macro and holder/on-chain with independently labeled Bitview alternatives. Additional peripheral indicators would not repair the failure classes addressed here.
- Native depth ±1% remains incomplete for many of 11 chosen markets and historical L2 gaps persist under the separate backfill. This is an **explicit optional-depth limitation**, not a reason to mark all BTC trend signals unavailable.
- Three original BGeometrics on-chain cost-basis series publish with delay; **do not** substitute the independent Bitview 150-day UTXO method under the old series name.
- Extreme outages disabling GitHub Actions itself need **external** verification: the hourly ChatGPT automation already checks health-report age and independently reads sources if it is missing or stale. Absence of a live-market shock is not evidence of perfect recall; missed/false model decisions still require subsequent real-message assessment.

### Outcome

**Item 6 technical reliability acceptance: satisfied for current operation**, with explicit limits above. Reopen only on a real, materially relevant failed collector, a confidence-gate contradiction, or a demonstrable missed/false user alert. Do not endlessly add minor indicators or rerun restricted endpoints.
