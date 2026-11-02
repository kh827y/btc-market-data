"""Live integration test: recover a deliberately missing BTC-USD hour in memory.

Never edits state.json or market data. Compare against independently archived,
fully trade-ID-verified Coinbase reference from the 12-shard full backfill.
"""
import datetime as dt
import json
from pathlib import Path
from coinbase_recent_repair import repair
from coinbase_parallel_backfill import utc,hour_key,UTC

state=json.loads(Path("btc-spot-cvd/data/state.json").read_text())
archive=json.loads(Path("btc-spot-cvd/data/coinbase_full_backfill_status.json").read_text())
anchor=utc(archive["anchor_hour"])
reference=state["hourly"]["coinbase"][hour_key(anchor)]
assert reference.get("integrity")=="id_continuous_verified"
assert reference.get("trades",0)>0
# Clock is pinned to the historical anchor's normal collection moment.
# Only an isolated empty in-memory working state gets repaired.
fake_now=anchor+dt.timedelta(hours=2,minutes=15)
test_state={"hourly":{"coinbase":{}}}
errors=[]
result=repair(test_state,fake_now,errors,pages=180,horizon=1)
actual=test_state["hourly"]["coinbase"].get(hour_key(anchor))
if actual is None:
    raise AssertionError("Real source did not restore missing Coinbase UTC hour: "+str(result))
if actual.get("integrity")!="id_continuous_verified" or errors:
    raise AssertionError("Recovered Coinbase hour not fully ID-verified: "+str(errors))
if actual["trades"]!=reference["trades"]:
    raise AssertionError("Coinbase page continuity trade count mismatch")
for metric in ("buy","sell","net"):
    if abs(float(actual[metric])-float(reference[metric]))>0.02:
        raise AssertionError("Coinbase live recovered "+metric+" differs from fully validated archive")
if result["status"]!="complete" or result["hours_remaining"]!=0:
    raise AssertionError("Coinbase repair did not close the UTC hour gap")
receipt={"tested_utc":dt.datetime.now(UTC).isoformat(),
         "verified":True,"scope":"real independent Coinbase REST read, isolated one-hour gap",
         "hour_restored":hour_key(anchor),"trade_count":actual["trades"],
         "old_verified_trade_count":reference["trades"],
         "buy_sell_net_match_reference_within_2c":True,
         "id_continuity_verified":True,
         "pages_scanned":result["pages_scanned"],
         "canonical_state_modified":False,
         "full_backfill_anchor":archive["anchor_hour"],
         "source":"Coinbase Exchange BTC-USD official REST"}
out=Path("btc-spot-cvd/data/coinbase_recent_repair_test.json")
out.write_text(json.dumps(receipt,indent=2)+"\n")
print(json.dumps(receipt))
