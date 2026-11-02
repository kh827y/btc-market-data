# BTC monitor — item 8: unify, shorten and verify the hourly automation policy

## Original requested objective
Replace the old roughly 99k-character stack of conflicting appended monitoring
instructions with ONE concise, source-controlled, noncontradictory working prompt.
Protect freshness, substantive directional risk, fact checking, no-spam policy,
explicit data limitations and notification format without wasting calls on low
value metrics. Then verify both the **actual enabled ChatGPT automation** and
its GitHub tests.

## Implemented, observed 2026-11-02 UTC

1. **Single source of truth:** [automation_prompt_v2.md](automation_prompt_v2.md)
   exactly equals the **actual enabled** automation named
   `Новости и риски BTC` (ID `6ae7be21dfc48191b5f4177180571e4e`),
   as proven by a fresh independent read-back of both surfaces at
   **22:42:51 UTC**. Canonical Git blob SHA:
   `02c464664db3cb21a105dafc281e947502739706`.
2. **Size:** 18,191 characters, down from the earlier 19,980-character
   live draft and the original approximately 99k-character historic prompt.
   Consolidation retained a single health-check section and one copy of
   the per-metric quality gate and actual depth/coverage caveats.
3. **Evidence semantics preserved:** read GitHub watchdog first;
   stale/missing source never equals zero; each eligible current
   metric has a fresh parent and `status=usable`; CVD uses actual
   executed spot trades; derivatives/option data and correlated
   price-family factors aren't counted as independent votes.
   No proxy is silently substituted for another BTC market/cohort.
4. **Signal logic retained:** two independently corroborating *material*
   evidence groups for ordinary trend warnings, with a verified systemic
   shock exception; early bullish and bearish risks, meaningful range
   signals, and anti-spam duplicate suppression. News fact truth is
   separate from BTC significance; no unconditional hourly status alerts.
5. **Publication rules retained:** Russian concise messages,
   important changed factors enumerated, conditional confirmation and
   invalidation, source links for factual news, and one final scoped
   data-status line only when a genuine alert is sent.
6. **No changes to the schedule:** the actual automation remains enabled
   with its original hourly schedule:
   `DTSTART:20261101T223405Z`,
   `RRULE:FREQ=HOURLY`. Separate BTC L2 backfill is unmodified.

### Verified real GitHub tests after update

- [CI run 41539303227](https://github.com/kh827y/btc-market-data/actions/runs/41539303227)
  passed with unified prompt committed.
- [CI run 41539417012](https://github.com/kh827y/btc-market-data/actions/runs/41539417012)
  passed with additional prompt-contract regression cases:
  exact unique section headings, watchdog status, native depth scope,
  independent evidence rules and no nonexistent fields.
- [policy_test_status.json](data/policy_test_status.json) reported both
  bridge quality and prompt-contract tests `true` at **22:41:55 UTC**.
- [metric_quality_acceptance.json](data/metric_quality_acceptance.json):
  `verified`, **195 metric checks**, **0 critical issues** at
  **22:41:55 UTC**.
- [health_latest.json](data/health_latest.json):
  `healthy`, **14 sources checked**, no unavailable/degraded
  controller inputs at **22:42:51 UTC**.
- [prompt_sync_acceptance.json](data/prompt_sync_acceptance.json)
  contains the direct one-time live-task equality evidence and exact
  schedule. This is a **point-in-time receipt**, not continuous proof
  of future equality.

## Final acceptance & important separation

**Item 8 — prompt minimization, deduplication, actual-task synchronization
and GitHub regression — VERIFIED.**

The active task's next real *model* run after this prompt replacement has
not been observed at acceptance timestamp. Existing hourly execution prior
to the change, and CI tests after it, should not be mislabeled a post-change
ChatGPT delivery test.

The separate item 7 **seven-day live decision and notification
acceptance remains IN PROGRESS** and cannot be waived by this item.
[decision_7day_observations.json](data/decision_7day_observations.json)
records actual hours and is not permitted to invent future observations.
One-time audit `Аудит 7 дней BTC` was already scheduled on
**2026-11-10 22:34 UTC** to review actual receipts and model
observations. GitHub Actions cannot prove user push/mail delivery.

No new source was needed: the remaining limits involve optional 1%-wide
order book depth, upstream vendor cohort lag, and separately managed
historical L2 backfill. Adding peripheral indicators would not improve
the correctness of the decision instruction.
