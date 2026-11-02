# BTC hourly news and reversal-monitor decision acceptance scenarios

These are **counterfactual regression examples**, NOT current market facts,
and **not executed market-analysis notifications**. The model's real alert
decision must follow the canonical task text at
btc-monitor/automation_prompt_v2.md. Static/unit tests check structural
presence of these rules; an agent-side decision still requires real-time
facts and historical context.

| Case | Input to reason about | Correct action |
| --- | --- | --- |
| 1. RSI alone | RSI14 76 on a closed daily bar; no verified new weakness, funding or spot change | **SILENCE**; overbought is not an impending top |
| 2. Price cross alone | Price drops slightly below MA20 for one session; no new independent factor | **SILENCE**; no confirmed material trend change |
| 3. Single ETF outflow | One large, verified negative US spot BTC-ETF session with otherwise unchanged price/demand | Usually **SILENCE**; may discuss as context if separately alert-worthy news |
| 4. Source reports zero | Spot CVD 30d complete=false, net=null, three venues accessible | **SILENCE** on unproven conclusion; report gaps only if an actual alert is otherwise warranted |
| 5. Two independent risk shifts | Closed daily BTC structure breaks plus credible new loss of actual spot absorption and rising verified leverage risk | **CONSIDER ALERT** for horizon; must be material, genuinely new and dated; explain conditional invalidation |
| 6. Same event republished | Ten headlines repeat an already-verified policy decision with no new terms | **SILENCE**; no new event |
| 7. Viral misleading headline | Widely shared false claim about a passed law; official source shows only a consultation draft | **FACTCHECK ALERT** if mass misinformation meaningfully distorts BTC risk; separate truth from importance |
| 8. Real systemic shock | Verified major exchange insolvency / network critical incident with substantial BTC exposure | **ALERT** even if another data family is lagging; mark confidence limits and sources |
| 9. Two related indicators | MVRV and NUPL change in same direction without other independent signal | **SILENCE**; correlated on-chain valuation is one family |
| 10. Fresh GitHub, stale OI | Bridge as_of current, derivatives status stale, OI value appears recent in one old row | **DO NOT USE** OI as new confirming risk factor |
| 11. Fed broad USD only | FRED DTWEXBGS usable but Yahoo ICE DXY unavailable | Discuss broad trade-weighted USD by name, DXY **UNKNOWN**, never substitute one for the other |
| 12. Before US ETF close | ETF tracker unchanged on US holiday or before close | **NO ZERO / NO MISSING FLOW ALARM**, normal reporting lag |
| 13. Previous identical alert | Risk case already messaged 6h ago; no new independent observation | **SILENCE**; ordinary risk-update spacing 12–24h is a guide, not newness guarantee |
| 14. Meaningful downside escalation | After warning, actual new sell pressure plus deterioration in independent derivative position data | **ALERT** despite normal 12–24h interval only if change is genuinely important |
| 15. Early bullish reversal | Verified improvement in executed spot demand and reduced forced liquidations; daily/weekly trend not yet confirmed | **CONSIDER PRELIMINARY ALERT**, explicitly say it is not yet a confirmed trend reversal |
| 16. Confirmed regime shift | Closed daily/weekly BTC structure improves, multi-week spot absorption returns and independent risk conditions improve | **ALERT** if truly a new medium-term regime change; state confirm/invalidate conditions |
| 17. Microtrend in range | Range exists for weeks; new repeated absorption at support and genuine fresh spot demand | **CONSIDER RARE CONDITIONAL ALERT** for 1–4 weeks; identify range boundary, not an intraday signal |
| 18. Newly integrated API works | Collector and CI now green; no market or news change | **SILENCE**; successful technical update is not a BTC market alert |
| 19. Old data contradicts fresh | Spot books stale, CVD fresh; one unavailable exchange has a high old bid count | Exclude stale evidence, **DO NOT** synthesize "global buy wall" |
| 20. Unrelated new story | Famous executive publishes a BTC price prediction without trades, official policy or new testable evidence | Usually **SILENCE**, even if many press reposts |

## Required model-visible output when an alert actually passes

For a news-only alert: fact-check status, 0–3 exclamation marks for BTC
importance independently of truth, 1–2 source links, event and published
dates, material practical effect, and one final "Данные" status line.

For trend alerts: concise directional title, what changed and timescale,
what would confirm/invalidate the assessment; then
"Что повлияло на оценку: ..." with **all significant changed and
independently corroborated factors**; then one final
"Данные (часовой мониторинг): ..." or
"Данные (полный анализ): ..." with scoped source limitations.
Never transmit scenario rows or hourly "all clear" reports to the user.
