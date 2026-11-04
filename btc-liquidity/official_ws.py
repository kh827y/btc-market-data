"""Official BTC public LIVE order-book snapshots over WebSocket.

Only native mainnet public market data. No proxies, exchange substitution,
testnet, broker feeds, synthetic books, or restricted REST bypass. Snapshot
must identify correct venue/instrument and contain both book sides, source UTC
timestamp and exchange update sequence. Streams with deltas ONLY are ignored.
"""
from __future__ import annotations
import datetime as dt
import json
import time

UTC=dt.timezone.utc
BYBIT={
    "bybit_spot":{"url":"wss://stream.bybit.com/v5/public/spot",
                  "topic":"orderbook.1000.BTCUSDT","market":"spot"},
    "bybit_usdt_perp":{"url":"wss://stream.bybit.com/v5/public/linear",
                       "topic":"orderbook.1000.BTCUSDT","market":"perpetual"},
}
BINANCE_URL="wss://ws-fapi.binance.com/ws-fapi/v1"
RESPONSE_TIMEOUT_S=12
MAX_FRAMES=12
BINANCE_CONNECTION_ATTEMPTS=2
BINANCE_RETRY_DELAY_S=1.25

class UnverifiedBook(ValueError):
    pass

def valid_source_ms(ms,now=None):
    if isinstance(ms,bool) or ms is None:raise UnverifiedBook("missing exchange source timestamp")
    try: timestamp=int(ms)
    except (ValueError,TypeError):raise UnverifiedBook("bad exchange source timestamp")
    t=(now or dt.datetime.now(UTC)).timestamp()*1000
    if not -10000<=(t-timestamp)<=120000:raise UnverifiedBook("stale or future exchange timestamp")
    return timestamp

def payload_sides(bids,asks):
    if (not isinstance(bids,list) or not isinstance(asks,list)
            or len(bids)<10 or len(asks)<10):
        raise UnverifiedBook("missing orderbook snapshot sides or insufficient depth")
    return bids,asks

def bybit_snapshot(msg,venue):
    spec=BYBIT[venue]
    if not isinstance(msg,dict) or msg.get("topic")!=spec["topic"]:
        return None
    if msg.get("type")!="snapshot":
        return None  # NEVER treat a partial delta as a complete order book
    row=msg.get("data")
    if not isinstance(row,dict) or row.get("s")!="BTCUSDT":
        raise UnverifiedBook("Bybit snapshot mismatched BTCUSDT symbol")
    if not isinstance(row.get("u"),int) or row["u"]<1:
        raise UnverifiedBook("Bybit missing sequence update id")
    if not isinstance(row.get("seq"),int) or row["seq"]<1:
        raise UnverifiedBook("Bybit missing cross sequence")
    t=valid_source_ms(msg.get("ts"))
    bids,asks=payload_sides(row.get("b"),row.get("a"))
    return {"retCode":0,"result":{"b":bids,"a":asks,"ts":str(t),
            "u":row["u"],"seq":row["seq"],"s":"BTCUSDT"},
            "_transport":"bybit_official_ws_snapshot",
            "_source_url":spec["url"],
            "_snapshot_type":"snapshot"}

def binance_depth_response(msg,request_id):
    if not isinstance(msg,dict) or msg.get("id")!=request_id:
        return None
    if msg.get("status")!=200:
        raise UnverifiedBook("Binance official WS API non-success status")
    row=msg.get("result")
    if not isinstance(row,dict):
        raise UnverifiedBook("Binance WS depth result missing")
    if not isinstance(row.get("lastUpdateId"),int) or row["lastUpdateId"]<1:
        raise UnverifiedBook("Binance depth update ID absent")
    t=valid_source_ms(row.get("E") or row.get("T"))
    bids,asks=payload_sides(row.get("bids"),row.get("asks"))
    return {"bids":bids,"asks":asks,
            "E":t,"lastUpdateId":row["lastUpdateId"],
            "_transport":"binance_official_ws_api_depth",
            "_source_url":BINANCE_URL,
            "_snapshot_type":"orderbook_snapshot"}

def read_official_book(venue,connection_factory=None):
    if venue not in BYBIT and venue!="binance_usdm_perp":
        raise ValueError("Unsupported direct official WebSocket venue")
    if connection_factory is None:
        # Lazy import keeps stdlib-only unit test runners lightweight.
        from websocket import create_connection
        connection_factory=create_connection
    url=BYBIT[venue]["url"] if venue in BYBIT else BINANCE_URL
    connection=None
    try:
        connection=connection_factory(url,timeout=RESPONSE_TIMEOUT_S)
        if venue in BYBIT:
            topic=BYBIT[venue]["topic"]
            connection.send(json.dumps({"op":"subscribe","args":[topic]}))
        else:
            req_id="btc-depth-verified-"+str(int(time.time()*1000))
            connection.send(json.dumps({"id":req_id,"method":"depth",
                                        "params":{"symbol":"BTCUSDT","limit":1000}}))
        for frame_idx in range(MAX_FRAMES):
            try:msg=json.loads(connection.recv())
            except (ValueError,TypeError) as exc:
                raise UnverifiedBook("Malformed official websocket data") from exc
            if venue in BYBIT:
                result=bybit_snapshot(msg,venue)
            else:
                result=binance_depth_response(msg,req_id)
            if result is not None:
                return result
        raise UnverifiedBook("Official WebSocket provided no verified full snapshot")
    finally:
        if connection is not None:
            connection.close()

def _transient_binance_ws_error(exc):
    """Only short-lived transport/server failures warrant one more request.

    Handshake denial, source-identity/timestamp mismatches, 429 and invalid
    book data do not trigger retries or silently become a smaller book.
    WebSocketTimeoutException/ConnectionClosedException are websocket-client
    exceptions (not subclasses of built-in TimeoutError).
    """
    if isinstance(exc, UnverifiedBook):
        return False
    if isinstance(exc, (TimeoutError, ConnectionError, OSError, EOFError)):
        return True
    return type(exc).__name__ in (
        "WebSocketTimeoutException",
        "WebSocketConnectionClosedException",
    )


def read_binance_futures_book(connection_factory=None, sleep_fn=None):
    """Bounded official USD-M BTCUSDT depth snapshot, with one safe retry.

    The same official ws-fapi endpoint, same symbol, same 1000-level request
    is used on both attempts. No REST 403/451 workaround, proxy, replayed
    snapshot, artificial padding, or substitution from another market.
    """
    if sleep_fn is None:
        sleep_fn=time.sleep
    for attempt in range(BINANCE_CONNECTION_ATTEMPTS):
        try:
            result=read_official_book("binance_usdm_perp",connection_factory)
            result["_connection_attempts"]=attempt+1
            return result
        except Exception as exc:
            if (attempt+1>=BINANCE_CONNECTION_ATTEMPTS or
                    not _transient_binance_ws_error(exc)):
                raise
            sleep_fn(BINANCE_RETRY_DELAY_S)
    raise AssertionError("unreachable Binance retry loop")


# Gate's public V2 "futures.obu" channel provides native 400-level
# initial FULL snapshots (unlike Bybit full-depth delta-only channel).
# This is the same genuine Gate BTC_USDT perpetual, not another venue.
GATE_V2_URL="wss://fx-ws.gateio.ws/v4/ws/usdt"
GATE_V2_TOPIC="ob.BTC_USDT.400"

def gate_v2_snapshot(msg):
    if not isinstance(msg,dict) or msg.get("channel")!="futures.obu":
        return None
    if msg.get("error"):
        raise UnverifiedBook("Gate V2 subscription error")
    if msg.get("event")=="subscribe":
        if msg.get("result",{}).get("status")!="success":
            raise UnverifiedBook("Gate V2 subscription denied")
        return None
    if msg.get("event")!="update":
        return None
    row=msg.get("result")
    if not isinstance(row,dict) or row.get("s")!=GATE_V2_TOPIC:
        raise UnverifiedBook("Gate V2 wrong BTC_USDT instrument")
    if row.get("full") is not True:
        return None  # A delta cannot initialize an unknown 400-level book.
    if not isinstance(row.get("u"),int) or isinstance(row.get("u"),bool) or row["u"]<1:
        raise UnverifiedBook("Gate V2 full snapshot has no native update ID")
    stamp=valid_source_ms(row.get("t"))
    bids,asks=payload_sides(row.get("b"),row.get("a"))
    try:
        bid_rows=[{"p":str(p),"s":str(s)} for p,s in bids]
        ask_rows=[{"p":str(p),"s":str(s)} for p,s in asks]
    except (TypeError,ValueError) as exc:
        raise UnverifiedBook("Gate V2 malformed full depth levels") from exc
    bid_rows.sort(key=lambda x:float(x["p"]),reverse=True)
    ask_rows.sort(key=lambda x:float(x["p"]))
    return {"id":row["u"],"current":stamp/1000,
            "bids":bid_rows,"asks":ask_rows,
            "_transport":"gate_official_ws_v2_full_snapshot",
            "_source_url":GATE_V2_URL,
            "_snapshot_type":"native_full_400_snapshot"}

def read_gate_v2_book(connection_factory=None):
    if connection_factory is None:
        from websocket import create_connection
        connection_factory=create_connection
    connection=None
    try:
        connection=connection_factory(GATE_V2_URL,timeout=RESPONSE_TIMEOUT_S)
        connection.send(json.dumps({"time":int(time.time()),"channel":"futures.obu",
                                    "event":"subscribe","payload":[GATE_V2_TOPIC]}))
        # The server sends an initial full=true 400-level snapshot.
        # Never build it from deltas, never reuse an expired book.
        for _ in range(MAX_FRAMES):
            try: msg=json.loads(connection.recv())
            except (ValueError,TypeError) as exc:
                raise UnverifiedBook("Malformed Gate V2 WebSocket frame") from exc
            result=gate_v2_snapshot(msg)
            if result is not None:
                return result
        raise UnverifiedBook("Gate V2 returned no verified full snapshot")
    finally:
        if connection is not None:
            connection.close()
