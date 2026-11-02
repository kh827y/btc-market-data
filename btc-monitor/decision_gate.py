"""Fail-closed *editorial candidate* gate for BTC risk alerts.

This does not make trading predictions or send notifications. It checks that
candidate reasons point at genuinely usable source-metric proofs in the
validated GitHub risk bridge. An eligible candidate still requires a model
fact-check, significance judgement, independently dated market context, and
actual user-delivery decision.
"""
from __future__ import annotations
import datetime as dt
from collections import defaultdict

UTC=dt.timezone.utc
# Correlated indicators are counted as ONE independent decision channel.
GROUP={
    "price_technical":"price_execution",
    "spot_cvd":"price_execution",
    "derivatives":"leverage_options",
    "options":"leverage_options",
    "onchain":"holders",
    "macro_etf":"macro_etf",
    "live_depth":"visible_liquidity",
}
CURRENT_MAX_HOURS={
    "price_technical":27, # closed daily candles, NOT live tick
    "spot_cvd":5,
    "derivatives":6,
    "options":6,
    "onchain":84, # daily provider lag explicitly scoped by quality gate
    "macro_etf":96, # weekends/ETF publication delay explicitly scoped
    "live_depth":3,
}

def parse_timestamp(value):
    if not isinstance(value,str) or "T" not in value:
        return None
    try:
        t=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
    except (ValueError,OverflowError):
        return None
    return t.astimezone(UTC) if t.tzinfo is not None else None

def state(brief,evidence,now):
    """Classify evidence against *actual* per-metric bridge proof; no numeric inference."""
    if not isinstance(evidence,dict):
        return None,"not_a_record"
    key=evidence.get("metric_key")
    quality=(brief.get("metric_quality") or {}).get("checks") or {}
    proof=quality.get(key) if isinstance(key,str) else None
    if not isinstance(proof,dict) or proof.get("status")!="usable":
        return None,"metric_not_proven_usable"
    source=proof.get("source")
    if not isinstance(source,str) or (brief.get("sources") or {}).get(source,{}).get("status")!="fresh":
        return None,"parent_source_not_fresh"
    group=GROUP.get(source)
    if group is None:
        return None,"unsupported_source_family"
    # A model may *label* significance, but only after quoting a real usable
    # measurement; do not turn metrics into alerts from arbitrary thresholds.
    direction=evidence.get("direction")
    if direction not in ("up","down") or evidence.get("material") is not True:
        return None,"not_a_material_directional_change"
    observed=parse_timestamp(evidence.get("observed_at"))
    if observed is None:
        return None,"missing_observation_time"
    age_h=(now-observed).total_seconds()/3600
    if age_h < -0.1 or age_h > CURRENT_MAX_HOURS[source]:
        return None,"candidate_observation_outside_horizon"
    proof_time=parse_timestamp(proof.get("observed_at"))
    # Date-only metrics (ETF closing session/onchain) are legal, but the
    # candidate can never claim observation more recent than the source.
    if proof_time and observed > proof_time + dt.timedelta(hours=24):
        return None,"candidate_newer_than_source"
    return (group,direction,key),None

def evaluate(brief,candidate,now=None,last_alerts=None):
    """Return review/silence, never publish action. No unsupported probabilities."""
    now=now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("UTC-aware datetime required")
    now=now.astimezone(UTC)
    if not isinstance(brief,dict) or not isinstance(candidate,dict):
        return {"action":"silence","reason":"invalid_input"}
    event_id=candidate.get("event_key")
    if not isinstance(event_id,str) or not 3<=len(event_id)<=180:
        return {"action":"silence","reason":"undated_or_unidentified_event"}
    asof=parse_timestamp(brief.get("as_of_utc"))
    if asof is None or not -0.1<=(now-asof).total_seconds()/3600<=3:
        return {"action":"silence","reason":"bridge_not_fresh"}
    prior=(last_alerts or {}).get(event_id)
    # A stronger NEW escalation can bypass routine anti-spam intervals,
    # but no original evidence => cannot claim a new trend alert.
    escalation=candidate.get("verified_new_escalation") is True
    if prior and not escalation:
        return {"action":"silence","reason":"event_already_alerted"}
    if candidate.get("new_change") is not True:
        return {"action":"silence","reason":"no_new_material_change"}
    kind=candidate.get("kind")
    if kind=="technical_update":
        return {"action":"silence","reason":"technical_change_is_not_market_news"}
    if kind=="systemic":
        if candidate.get("first_party_confirmed") is True and candidate.get("material_to_btc") is True:
            return {"action":"review_exception","reason":"verified_systemic_shock",
                    "not_automatically_delivered":True}
        return {"action":"silence","reason":"systemic_claim_unverified"}
    if kind=="factcheck":
        if (candidate.get("primary_source_checked") is True and
            candidate.get("widely_circulated") is True and
            candidate.get("material_to_btc") is True):
            return {"action":"review_factcheck","reason":"significant_misinformation",
                    "not_automatically_delivered":True}
        return {"action":"silence","reason":"factcheck_not_worth_alert"}
    if kind!="trend" or candidate.get("direction") not in ("up","down"):
        return {"action":"silence","reason":"unsupported_alert_kind_or_direction"}
    if candidate.get("time_horizon") not in ("days_weeks","weeks_months","range_1_4_weeks"):
        return {"action":"silence","reason":"missing_usable_horizon"}
    if not candidate.get("confirmation_condition") or not candidate.get("invalidation_condition"):
        return {"action":"silence","reason":"missing_confirm_invalidate_conditions"}
    groups=defaultdict(set)
    excluded=[]
    for evidence in candidate.get("evidence") or []:
        item,error=state(brief,evidence,now)
        if error:
            excluded.append({"metric_key":evidence.get("metric_key") if isinstance(evidence,dict) else None,
                             "reason":error})
            continue
        group,direction,key=item
        if direction==candidate["direction"]:
            groups[group].add(key)
    if len(groups)<2:
        return {"action":"silence","reason":"fewer_than_two_independent_verified_groups",
                "verified_groups":sorted(groups),"excluded":excluded}
    # Approval is human/model editorial only; do not convert this gate into
    # an automated trade/no-trade score or a user notification.
    return {"action":"review","reason":"independent_candidate_for_editorial_factcheck",
            "verified_groups":sorted(groups),"verified_metric_keys":
                sorted({k for values in groups.values() for k in values}),
            "excluded":excluded,"not_automatically_delivered":True}
