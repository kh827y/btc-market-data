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

def fixture(missing_checkpoint=False):
    hour=int(dt.datetime(2026,10,31,12,tzinfo=dt.timezone.utc).timestamp()*1e9)
    data=[]
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
    def test_zstd_outer_frame_recovered(self):
        raw=fixture()
        packed=zstd.ZstdCompressor().compress(raw)
        record=m.parse_checkpoint(packed,"binance_spot","BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        self.assertEqual(record["snapshot_rows"],24)
    def test_no_snapshot_rejected(self):
        with self.assertRaisesRegex(ValueError,"missing hour-start checkpoint"):
            m.parse_checkpoint(fixture(True),"binance_spot","BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
    def test_null_missing_baseline(self):
        r=m.parse_checkpoint(fixture(),"binance_spot","BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        c,b=m.make_comparisons({"binance_spot":{"2026-10-31":{"status":"ok","data":r}}})
        self.assertIsNone(c["binance_spot"]["previous_days"]["7d"])
        self.assertIsNone(b["binance_spot"]["7d"]["bands"]["0.05"])
if __name__=="__main__":
    unittest.main()
