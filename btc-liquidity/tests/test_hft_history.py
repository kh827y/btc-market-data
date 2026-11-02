import datetime as dt
import importlib.util
import io
from pathlib import Path
import unittest

import pyarrow as pa
import pyarrow.parquet as pq
import zstandard as zstd

spec=importlib.util.spec_from_file_location("hft_history",Path(__file__).resolve().parents[1]/"hft_history.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def fixture(missing_checkpoint=False, delayed_checkpoint=False):
    hour=int(dt.datetime(2026,10,31,12,tzinfo=dt.timezone.utc).timestamp()*1e9)
    data=[]
    if delayed_checkpoint:
        data.append({"received_time":hour+int(5e9),"event_type":"update",
                     "side":"bid","price":"100","quantity":"3", "final_update_id":110})
        hour+=int(20*60*1e9)
    for side in ("bid","ask"):
        for n in range(12):
            price=(100-0.01*n if side=="bid" else 100.01+0.01*n)
            data.append({"received_time":hour,"event_type":"update" if missing_checkpoint else "snapshot",
                         "side":side,"price":str(price),"quantity":"2",
                         "final_update_id":111})
    data.append({"received_time":hour+int(1e9),"event_type":"update",
                 "side":"bid","price":"100","quantity":"1","final_update_id":112})
    f=io.BytesIO()
    pq.write_table(pa.Table.from_pylist(data),f)
    return f.getvalue()

class HistoricL2Tests(unittest.TestCase):
    def test_verified_checkpoint_depth(self):
        a=m.parse_checkpoint(fixture(),"binance_spot","BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        self.assertEqual(a["snapshot_rows"],24)
        self.assertEqual(a["levels"],{"bid":12,"ask":12})
        self.assertIsNotNone(a["bands"]["0.05"]["bid_share"])
        self.assertIsNone(a["bands"]["1.0"]["bid_share"])
    def test_later_verified_checkpoint_is_accepted(self):
        r=m.parse_checkpoint(fixture(delayed_checkpoint=True),"binance_spot",
            "BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        self.assertEqual(r["snapshot_rows"],24)
        self.assertEqual(r["sample_utc_hour"],12)
        self.assertEqual(dt.datetime.fromisoformat(r["time"]).minute,20)
    def test_failure_for_one_hour_does_not_blacklist_adjacent_hours(self):
        now=dt.datetime(2026,11,2,8,tzinfo=dt.timezone.utc)
        records={name:{} for name in m.MARKETS}
        failed={"binance_spot:2026-11-01:12":{
            "retry_after":(now+dt.timedelta(days=7)).isoformat()}}
        picked=[t for t in m.targets(dt.date(2026,11,1), records,failed,now)
                if t[0]=="binance_spot" and t[1]==dt.date(2026,11,1)]
        self.assertEqual([x[2] for x in picked],[11,13])
    def test_reject_different_time_of_day_for_baseline(self):
        last=m.parse_checkpoint(fixture(),"binance_spot",
            "BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        earlier=dict(last)
        earlier["time"]="2026-10-30T01:00:00+00:00"
        later=dict(last)
        later["time"]="2026-10-31T12:00:00+00:00"
        c,b=m.make_comparisons({"binance_spot":{
            "2026-10-30":{"status":"ok","data":earlier},
            "2026-10-31":{"status":"ok","data":later}}})
        self.assertIsNone(c["binance_spot"]["previous_days"]["1d"])
    def test_zstd_outer_frame_recovered(self):
        raw=fixture()
        packed=zstd.ZstdCompressor().compress(raw)
        record=m.parse_checkpoint(packed,"binance_spot","BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        self.assertEqual(record["snapshot_rows"],24)
    def test_no_snapshot_rejected(self):
        with self.assertRaisesRegex(ValueError,"no verified checkpoint snapshot"):
            m.parse_checkpoint(fixture(True),"binance_spot","BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
    def test_null_missing_baseline(self):
        r=m.parse_checkpoint(fixture(),"binance_spot","BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        c,b=m.make_comparisons({"binance_spot":{"2026-10-31":{"status":"ok","data":r}}})
        self.assertIsNone(c["binance_spot"]["previous_days"]["7d"])
        self.assertIsNone(b["binance_spot"]["7d"]["bands"]["0.05"])
if __name__=="__main__":
    unittest.main()
