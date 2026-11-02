# BTC item 7 — actual decision acceptance and seven-day live observation

## Scope / acceptance status

The agreed next stage is **end-to-end risk-notification acceptance**, not another
source-volume expansion. It calls for: (1) true material trend changes considered
in both directions; (2) ordinary/no-change periods silent; (3) contradictory or
stale evidence excluded; (4) failure of an essential source reported appropriately;
(5) genuinely delivered notifications verified if observable; (6) at least
**seven consecutive real calendar days** of monitoring. Passing unit tests
alone **does not close** the full item.

**Current status as of 2026-11-02 22:31 UTC: core decision and data-integrity
tests pass, hourly verification running, seven-day observation and
notification-delivery evidence still PENDING.** Never claim the full criterion
is satisfied without actual elapsed time and independent evidence.

## Production implementation

- [`btc-monitor/decision_gate.py`](decision_gate.py) verifies a *candidate*:
  canonical per-metric proof in the actual compact brief, `status=usable`,
  fresh parent family, unit, scope, real metric time, prospective horizon,
  genuine material change, a unique event key, duplicate suppression and
  explicit confirmation/invalidation. Price plus spot CVD count as **one**
  broad demand/execution family, derivatives plus options as **one**
  positioning family; distinct holder, macro/ETF and visible liquidity evidence
  may corroborate. A verified systemic shock and consequential false headline
  have separately dated editorial exception paths. It returns `review` or
  `silence`, **never a user alert or market prediction**.
- [`btc-monitor/tests/test_decision_gate.py`](tests/test_decision_gate.py)
  tests downside/upside, sideways, stale CVD/OI, related MVRV/NUPL,
  incomplete books, new meaningful escalation vs duplicates, shock,
  misleading headline, missing dates/sources and required conditions.
- The **active hourly ChatGPT automation** and the versioned
  [`automation_prompt_v2.md`](automation_prompt_v2.md) now explicitly require
  the same canonical proof checks and broad-family independence before any
  actual message. This is an active *instruction*, not proof that future
  model decisions will always be correct.
- [`btc-monitor/decision_observations.py`](decision_observations.py) runs
  hourly from its dedicated public GitHub Actions job
  [`btc-decision-acceptance.yml`](../.github/workflows/btc-decision-acceptance.yml).
  It checks live bridge, independent watchdog, 195-metric quality acceptance,
  tested policy and fresh essential source families. It also sends two
  **real actual-data proof rows** (CVD and OI) into the candidate gate with
  **clearly fabricated counterfactual direction/materiality flags** solely to
  verify integration, NEVER as a market signal.
- [`btc-monitor/data/decision_7day_observations.json`](data/decision_7day_observations.json)
  is an append-by-actual-UTC-hour ledger; it NEVER backfills missed hours
  using yesterday's data, counts restarts as extra hours or assumes a
  green CI job is a platform notification. Passing a **168 elapsed hour**
  window requires **at least 169 successive distinct ready hourly receipts**.
  Any source-quality fault or missed UTC hour breaks continuity.
- Unit tests in
  [`btc-monitor/tests/test_decision_observations.py`](tests/test_decision_observations.py)
  check seven-day qualification, gaps, duplicates, degraded source quality,
  actual compact proof schema and artificial vs real distinctions.
- User's separate `Дозагрузка истории BTC L2` remains unchanged. No
  restricted/exhausted provider is polled just to inflate completeness.

## Real verified evidence

- [First dedicated GitHub Actions test run, success](https://github.com/kh827y/btc-market-data/actions/runs/41537464123).
- [Post-fix real-brief candidate integration, success](https://github.com/kh827y/btc-market-data/actions/runs/41537926244).
- Actual UTC 2026-11-02 **22:31:08** record confirmed one real
  `ready` hour, `metric_checks:195` and
  `real_source_gate_smoke.status:passed`. The simulated test direction
  is *not* an actual short-side warning. The seven-day field was
  `verified:false`, `consecutive_ready_hour_checkpoints:1`.
- Existing upstream
  [`metric_quality_acceptance.json`](data/metric_quality_acceptance.json)
  and [`health_latest.json`](data/health_latest.json) have separately
  reported `verified` and `healthy`, with zero critical issue flags.
- Explicit external one-time ChatGPT scheduled check:
  **2026-11-10 22:34 UTC**, title `Аудит 7 дней BTC`, verifies actual
  169 checkpoints and task evidence independently. It will not relabel
  GitHub CI as proven user push/email delivery.

## Remaining non-bypassable acceptance conditions

- **Actual elapsed seven days** with completed hourly ledger; a few
  successful short CI runs are insufficient. As of creation there are
  fewer than 169 checkpoints.
- **Real world sensitivity and false-alert rate** require looking at actual
  major BTC events and the ChatGPT task's real alert decisions over that
  period. Synthetic scenarios cannot prove that all significant events
  were found.
- **Delivery to user**: GitHub has no authority to inspect ChatGPT push,
  mail or client receipt; a ChatGPT automation run marked completed alone
  does not prove user delivery. Record the limitation rather than
  inventing proof. Do not force noisy synthetic alerts solely to check
  notifications without an explicit user request.

The implementation is ready; the seven-day external acceptance milestone
remains explicitly **IN PROGRESS**. Additional low-value book-depth or
esoteric cycle metrics do not solve this problem.
