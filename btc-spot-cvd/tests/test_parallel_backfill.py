import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from backfill_parallel import merge, VENUES
from collector import key,UTC


class ParallelBackfillTests(unittest.TestCase):
    def setup_input(self,base):
        now=dt.datetime.now(UTC)
        hour=now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=2)
        k=key(hour)
        artifacts=Path(base)/"artifacts"
        repo=Path(base)/"repo"
        (repo/"btc-spot-cvd/data").mkdir(parents=True)
        prior={"hourly":{"coinbase":{k:{"hour":k,"net":7,"complete":True}}}}
        (repo/"btc-spot-cvd/data/state.json").write_text(json.dumps(prior))
        for venue in VENUES:
            f=artifacts/venue/"result.json"
            f.parent.mkdir(parents=True)
            f.write_text(json.dumps({"venue":venue,"attempted":720,
              "end_utc":k,"data":{k:{"complete":True,"hour":k,"net":3,
                                      "source":"CryptoHFTData"}},"errors":[]}))
        return repo,artifacts,k

    def test_merge_keeps_coinbase_and_adds_exact_alternate_venues(self):
        with tempfile.TemporaryDirectory() as work:
            repo,artifacts,k=self.setup_input(work)
            merge(artifacts,repo)
            state=json.loads((repo/"btc-spot-cvd/data/state.json").read_text())
            self.assertEqual(state["hourly"]["coinbase"][k]["net"],7)
            for venue in VENUES:
                self.assertEqual(state["hourly"][venue][k]["net"],3)
            latest=json.loads((repo/"btc-spot-cvd/data/latest.json").read_text())
            self.assertTrue(latest["windows"]["1h"]["complete"])
            self.assertEqual(latest["windows"]["1h"]["net"],19)
            self.assertTrue(latest["windows"]["1h"]["fixed_five_ex_coinbase"]["complete"])
            self.assertEqual(latest["windows"]["1h"]["fixed_five_ex_coinbase"]["net"],15)
            self.assertFalse(latest["windows"]["24h"]["complete"])

    def test_merge_rejects_missing_venue_artifact(self):
        with tempfile.TemporaryDirectory() as work:
            repo,artifacts,k=self.setup_input(work)
            (artifacts/"bitget/result.json").unlink()
            with self.assertRaises(RuntimeError):
                merge(artifacts,repo)

if __name__=="__main__":
    unittest.main()
