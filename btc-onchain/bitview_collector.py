"""Daily Bitview history. LTH threshold: 150 days (not Glassnode 155)."""
import datetime as dt
import json
import pathlib
import urllib.request

SERIES = {
    "lth_supply_150d": "lth_supply",
    "sth_supply_150d": "sth_supply",
    "lth_change_30d_150d": "lth_supply_delta_1m",
    "lth_change_7d_150d": "lth_supply_delta_1w",
    "lth_realized_price_150d": "lth_realized_price",
    "sth_realized_price_150d": "sth_realized_price",
    "realized_price_bitview": "realized_price",
    "lth_nupl_150d": "lth_nupl",
    "sth_nupl_150d": "sth_nupl",
}
