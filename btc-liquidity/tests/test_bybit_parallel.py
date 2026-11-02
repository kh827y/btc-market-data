import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import bybit_parallel_backfill as bp

UTC=dt.timezone.utc

class ParallelBybitTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,11,2,8,tzinfo=UTC)
        self.start=dt.date(2026,10,10)
        self.venue_starts={
            "bybit_independent_linear":("linear",self.start),
            "bybit_independent_spot":("spot",self.start)}
    def mock_blocks(self,dir):
        through=dt.date(2026,11,1)
        total=(through-self.start).days+1
        for cat,parts in bp.SHARDS.items():
            for shard in range(parts):
                dates=[self.start+dt.timedelta(days=i) for i in range(shard,total,parts)]
                venue=bp.NAME[cat]
                rows={}
                for day in dates:
                    s=day.isoformat()
                    rows[s]={"time":f"{s}T00:00:01+00:00",
                             "venue":venue,"market":"spot" if cat=="spot" else "perpetual",
                             "source_type":"independent Bybit daily native snapshot",
                             "bands":{x:{"bid_share":0.6 if x=="0.01" else None,
                                         "bid_usd":500.0 if x=="0.01" else None,
                                         "ask_usd":333.0 if x=="0.01" else None}
                                      for x in ("0.01","0.05","0.2","1.0")}}
                path=pathlib.Path(dir)/f"{cat}-{shard}"/"result.json"
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps({"status":"done","category":cat,"venue":venue,
                    "shard":shard,"shards":parts,"through":str(through),
                    "attempted":len(dates),"records":rows,"errors":{}}))
    def test_complete_disjoint_shards_merge_preserves_records_and_recomputes(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            self.mock_blocks(root/"artifacts")
            original=root/"repo"/"btc-liquidity/data"
            original.mkdir(parents=True)
            k="2026-11-01"
            old={"records":{"bybit_independent_linear":{
                k:{"time":"2026-11-01T00:00:02+00:00","venue":"bybit_independent_linear",
                   "market":"perpetual","source_type":"independent Bybit daily native snapshot",
                   "bands":{x:{"bid_share":0.5 if x=="0.01" else None,
                               "bid_usd":200 if x=="0.01" else None,
                               "ask_usd":200 if x=="0.01" else None}
                            for x in ("0.01","0.05","0.2","1.0")}}}},
                 "failures":{}}
            (original/"bybit_independent_history.json").write_text(json.dumps(old))
            with patch.dict(bp.bi.VENUES,self.venue_starts,clear=True):
                bp.merge(root/"artifacts",root/"repo",self.now)
            history=json.loads((original/"bybit_independent_history.json").read_text())
            latest=json.loads((original/"bybit_independent_latest.json").read_text())
            self.assertEqual(latest["status"],"ok")
            self.assertEqual(latest["coverage"]["bybit_independent_spot"]["verified_days"],23)
            self.assertEqual(latest["coverage"]["bybit_independent_linear"]["verified_days"],23)
            self.assertEqual(history["records"]["bybit_independent_linear"][k]["bands"]["0.01"]["bid_share"],0.5)
            self.assertIsNotNone(latest["comparisons"]["bybit_independent_spot"]["comparisons"]["1d"])
    def test_source_date_audit_preserves_explicit_unverified_day(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            self.mock_blocks(root/"artifacts")
            path=root/"artifacts"/"spot-0"/"result.json"
            block=json.loads(path.read_text())
            missing=next(iter(block["records"]))
            del block["records"][missing]
            block["errors"][missing]="ValueError: initial snapshot not near midnight UTC; offset_seconds=400.000"
            path.write_text(json.dumps(block))
            with patch.dict(bp.bi.VENUES,self.venue_starts,clear=True):
                bp.merge(root/"artifacts",root/"repo",self.now)
            status=json.loads((root/"repo"/"btc-liquidity/data"/"bybit_full_backfill_status.json").read_text())
            audit=status["day_audit"]["bybit_independent_spot"]
            self.assertTrue(status["all_source_dates_accounted_for"])
            self.assertEqual(audit["eligible_days"],23)
            self.assertEqual(audit["verified_days"],22)
            self.assertEqual(audit["explicit_error_days"],1)
            self.assertEqual(audit["unaccounted_days"],[])
            self.assertEqual(audit["unverified_dates"][0]["day"],missing)

    def test_merge_accepts_real_snapshot_three_ms_before_midnight(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            self.mock_blocks(root/"artifacts")
            p=root/"artifacts"/"linear-1"/"result.json"
            blob=json.loads(p.read_text())
            day=next(iter(blob["records"]))
            stamp=dt.datetime.combine(dt.date.fromisoformat(day),dt.time(),UTC)-dt.timedelta(milliseconds=3)
            blob["records"][day]["time"]=stamp.isoformat()
            p.write_text(json.dumps(blob))
            with patch.dict(bp.bi.VENUES,self.venue_starts,clear=True):
                bp.merge(root/"artifacts",root/"repo",self.now)
            state=json.loads((root/"repo"/"btc-liquidity/data"/"bybit_full_backfill_status.json").read_text())
            self.assertEqual(state["day_audit"]["bybit_independent_linear"]["verified_days"],23)

    def test_merge_rejects_source_snapshot_too_far_before_midnight(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            self.mock_blocks(root/"artifacts")
            p=root/"artifacts"/"linear-1"/"result.json"
            blob=json.loads(p.read_text())
            day=next(iter(blob["records"]))
            stamp=dt.datetime.combine(dt.date.fromisoformat(day),dt.time(),UTC)-dt.timedelta(milliseconds=11)
            blob["records"][day]["time"]=stamp.isoformat()
            p.write_text(json.dumps(blob))
            with patch.dict(bp.bi.VENUES,self.venue_starts,clear=True):
                with self.assertRaisesRegex(ValueError,"provenance"):
                    bp.merge(root/"artifacts",root/"repo",self.now)

    def test_inconsistent_shard_through_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            self.mock_blocks(root/"artifacts")
            path=root/"artifacts"/"linear-1"/"result.json"
            block=json.loads(path.read_text())
            block["through"]="2026-10-31"
            path.write_text(json.dumps(block))
            with patch.dict(bp.bi.VENUES,self.venue_starts,clear=True):
                with self.assertRaisesRegex(ValueError,"inconsistent"):
                    bp.merge(root/"artifacts",root/"repo",self.now)

    def test_missing_shard_dates_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            self.mock_blocks(root/"artifacts")
            f=root/"artifacts"/"linear-1"/"result.json"
            blob=json.loads(f.read_text())
            del blob["records"][next(iter(blob["records"]))]
            f.write_text(json.dumps(blob))
            with patch.dict(bp.bi.VENUES,self.venue_starts,clear=True):
                with self.assertRaisesRegex(ValueError,"missing dates"):
                    bp.merge(root/"artifacts",root/"repo",self.now)
    def test_misnamed_venue_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            self.mock_blocks(root/"artifacts")
            f=root/"artifacts"/"spot-1"/"result.json"
            blob=json.loads(f.read_text())
            k=next(iter(blob["records"]))
            blob["records"][k]["venue"]="bybit_independent_linear"
            f.write_text(json.dumps(blob))
            with patch.dict(bp.bi.VENUES,self.venue_starts,clear=True):
                with self.assertRaisesRegex(ValueError,"provenance"):
                    bp.merge(root/"artifacts",root/"repo",self.now)

if __name__=="__main__":unittest.main()
