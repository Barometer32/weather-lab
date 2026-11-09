"""Minnesota HFMETAR timing audit and shared source downloads."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import gzip
from io import BytesIO
import math
import statistics
from urllib.error import HTTPError

KEY = "live/mn-asos-audit-v1.json"
# Active Minnesota airport IDs from Iowa State's MN_ASOS network inventory.
# Many of these are AWOS sites that do not appear in MADIS HFMETAR.
STATIONS = frozenset("K" + code for code in """
04W 14Y 21D 3N8 9MN ACQ ADC AEL AIT ANE AQP AUM AXN BBB BDE BDH BJI BRD
CBG CDD CFE CKC CKN CNB COQ CQM D39 DLH DTL DVP DXX DYT ELO ETH EVM FBL
FCM FFM FGN FKA FOZ FRM FSE GDB GHW GNA GPZ GYL HCD HCO HIB HZX INL JKJ
JMR JYG LJF LVN LXL LYV MGG MIC MJQ MKT MML MOX MSP MVE MWM MZH ONA ORB
OTG OVL OWA PEX PKD PNM PQN PWC RGK ROS ROX RRT RST RWF RYM SAZ SGS STC
STP SYN TKC TOB TVF TWM ULM VVV VWU XVG Y49 Y63
""".split())
WINDOW = 48 * 3600


def parse_timing(payload):
    from scipy.io import netcdf_file

    with gzip.GzipFile(fileobj=BytesIO(payload)) as stream:
        content = stream.read(30_000_001)
    if len(content) > 30_000_000:
        raise ValueError("MADIS timing file exceeds expected size")
    with netcdf_file(BytesIO(content), mmap=False) as dataset:
        v = dataset.variables
        for ident, obs, received in zip(v["stationId"][:], v["observationTime"][:], v["receivedTime"][:]):
            station = ident.tobytes().decode("ascii", errors="replace").strip("\0 ")
            if station not in STATIONS or not math.isfinite(obs) or not 0 < obs < 4_000_000_000:
                continue
            arrival = int(received) if math.isfinite(received) and obs <= received < 4_000_000_000 else None
            yield station, int(obs), arrival


def collect(store, now, download=None, *, publish_observations=False):
    from madis_observations import fetch_file, file_url

    download = download or fetch_file
    stamp = int(now.timestamp())
    old = store.read_json(KEY) or {}
    start = max(old.get("startedAt", stamp), stamp - WINDOW)
    polls = {p[0]: p for p in old.get("polls", []) if p[0] >= start}
    reports = {(s, obs): [s, obs, received, seen] for s, obs, received, seen in old.get("reports", [])
               if obs >= stamp - WINDOW}
    hour = now.replace(minute=0, second=0, microsecond=0)

    def read(target):
        try:
            payload = download(file_url(target))
            return list(parse_timing(payload)), None, payload
        except (HTTPError, TimeoutError, OSError, ValueError, KeyError) as error:
            return [], f"{target:%Y%m%d_%H} UTC: {error}"[:200], None

    targets = (hour, hour - timedelta(hours=1))
    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(read, targets))
    errors = [error for _, error, _ in batches if error]
    for batch, _, _ in batches:
        for station, obs, received in batch:
            if not stamp - WINDOW <= obs <= stamp:
                continue
            entry = reports.setdefault((station, obs), [station, obs, received, stamp])
            if received is not None and (entry[2] is None or received < entry[2]):
                entry[2] = received
    polls[stamp] = [stamp, errors]
    data = {"startedAt": start, "checkedAt": stamp, "polls": [polls[t] for t in sorted(polls)],
            "reports": list(reports.values())}
    store.write_json(KEY, data)
    if len(errors) == len(batches):
        raise RuntimeError("Neither MADIS hour file was available: " + "; ".join(errors))
    result = {"stations": len({row[0] for row in data["reports"] if row[1] >= stamp - 3600}),
              "reports": len(reports), "fileErrors": errors}
    if publish_observations:
        from rolling_observations import prepare
        result["observations"] = prepare(store, now, ((h, p) for h, (_, _, p) in reversed(list(zip(targets, batches))) if p is not None))
    return result


def summarize(data):
    by_station = defaultdict(list)
    gaps = Counter()
    delays = []
    source_delays = []
    first_poll = data["startedAt"]
    for station, obs, received, seen in data["reports"]:
        by_station[station].append(obs)
        # Exclude initial backfill from measured poll latency.
        if obs >= first_poll:
            delays.append(seen - obs)
            if received is not None:
                source_delays.append(received - obs)
    station_gaps = {}
    for station, timestamps in sorted(by_station.items()):
        timestamps.sort()
        seconds = [b - a for a, b in zip(timestamps, timestamps[1:])]
        gaps.update(seconds)
        station_gaps[station] = {"reports": len(timestamps), "longestGapMinutes": max(seconds, default=0)/60,
                                 "gapsAtLeast20Minutes": sum(x >= 1200 for x in seconds),
                                 "latestReportAgeMinutes": (data["checkedAt"] - timestamps[-1])/60}
    def latency(samples):
        values = sorted(samples)
        return None if not values else {
            "count": len(values), "medianMinutes": round(statistics.median(values)/60, 1),
            "p95Minutes": round(values[math.ceil(.95*len(values))-1]/60, 1),
            "maxMinutes": round(values[-1]/60, 1), "atLeast20Minutes": sum(x >= 1200 for x in values)}
    return {"monitoringStartedUTC": datetime.fromtimestamp(first_poll, timezone.utc).isoformat(),
            "latestPollUTC": datetime.fromtimestamp(data["checkedAt"], timezone.utc).isoformat(),
            "polls": len(data["polls"]), "pollsWithFileErrors": sum(bool(e) for _, e in data["polls"]),
            "reportGapCountsByMinutes": {s/60: n for s, n in sorted(gaps.items())},
            "madisReceiptLag": latency(source_delays), "firstSeenByPollLag": latency(delays),
            "stations": station_gaps}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(summarize(json.load(sys.stdin)), indent=2))
