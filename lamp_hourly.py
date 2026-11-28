"""The next 24 hours from NOAA's operational, station-based LAMP bulletin."""
from datetime import datetime, timedelta, timezone
from math import atan2, cos, degrees, floor, hypot, radians, sin
import re
from statistics import mean
from urllib.error import HTTPError, URLError

STATIONS = ("KMSP", "KFCM", "KMIC")
HORIZON = 24
MODEL_HOUR = timedelta(hours=1)
SNAPSHOT_KEY = "live/hourly.json"
BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/lmp/prod"
HEADER = re.compile(r"^([A-Z0-9]{4})\s+.*?\bGFS[- ]+LAMP\b(.*)$")
ROWS = {"UTC", "TMP", "DPT", "WSP", "WDR", "CLD", "CIG", "P01"}
CLOUD_OCTAS = {"CL": 0, "FW": 1.5, "SC": 3.5, "BK": 6, "OV": 8}
CEILING_FEET = {1: 100, 2: 300, 3: 700, 4: 1450, 5: 2500, 6: 4800, 7: 9300, 8: 12000}
KNOT_TO_MPH = 1.150779448


def iso(timestamp):
    return timestamp.isoformat().replace("+00:00", "Z")


def latest_cycle(now):
    # The :30 label is the model cycle. Allow until :55 for dissemination.
    return (now - timedelta(minutes=55)).replace(minute=30, second=0, microsecond=0)


def first_valid(cycle):
    return cycle.replace(minute=0) + MODEL_HOUR


def bulletin_url(cycle):
    return f"{BASE_URL}/lmp.{cycle:%Y%m%d}/lmp.t{cycle:%H%M}z.lavtxt.ascii"


def parse_bulletin(document, cycle):
    blocks = {}
    current = None
    for raw_line in document.splitlines():
        line = raw_line.lstrip()
        header = HEADER.match(line)
        if header:
            station, stamp = header.groups()
            current = None
            if station in STATIONS:
                day = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", stamp)
                clock = re.search(r"\b(\d{4})\s+UTC\b", stamp)
                if not day or not clock:
                    raise ValueError(f"LAMP cycle timestamp missing for {station}")
                stamped_cycle = datetime.strptime(
                    f"{day[0]} {clock[1]}", "%m/%d/%Y %H%M",
                ).replace(tzinfo=timezone.utc)
                if stamped_cycle != cycle or station in blocks:
                    raise ValueError(f"LAMP cycle mismatch or duplicate block for {station}")
                current = blocks[station] = {}
            continue
        key = line[:3]
        if current is None or key not in ROWS:
            continue
        # Row IDs have a separator before the three-character forecast fields.
        # The fixed width retains negatives, blanks and consecutive 100s.
        current[key] = [line[4 + i * 3:7 + i * 3].strip() for i in range(HORIZON + 1)]

    expected_hours = [
        f"{(first_valid(cycle) + i * MODEL_HOUR).hour:02d}" for i in range(HORIZON + 1)
    ]
    for station in STATIONS:
        block = blocks.get(station, {})
        if not ROWS.issubset(block) or block["UTC"] != expected_hours:
            raise ValueError(f"LAMP station or hourly fields missing for {station}")
    return blocks


def numeric(text, low, high):
    try:
        value = int(text)
    except ValueError:
        return None
    return value if low <= value <= high else None


def average(values):
    return mean(values) if None not in values else None


def nearest(value):
    return floor(value + 0.5) if value is not None else None


def wind(speeds, directions):
    knots = average(speeds)
    if knots is None:
        return None, None
    mph = nearest(knots * KNOT_TO_MPH)
    if mph <= 3:
        return mph, None

    vectors = [
        (speed, radians(direction * 10))
        for speed, direction in zip(speeds, directions)
        if speed > 0 and direction is not None
    ]
    east = sum(speed * sin(angle) for speed, angle in vectors)
    north = sum(speed * cos(angle) for speed, angle in vectors)
    if hypot(east, north) < 1e-6:
        return mph, None
    return mph, degrees(atan2(east, north)) % 360


def clouds(cover, ceiling):
    octas = average([CLOUD_OCTAS.get(code) for code in cover])
    if octas is None:
        return None, None
    label = next(name for cutoff, name in [
        (0.5, "Clear"), (2.5, "Few"), (4.5, "Scattered"), (7.5, "Broken"), (9, "Overcast"),
    ] if octas < cutoff)
    if label not in ("Broken", "Overcast"):
        return label, None
    codes = [code for cloud, code in zip(cover, ceiling) if cloud in ("BK", "OV")]
    if not codes or None in codes:
        return label, None
    if all(code == 8 for code in codes):
        return label, ">12k"
    # In a mixed case use 12,000 ft as the lower bound of an open category.
    thousands = nearest(mean(CEILING_FEET[code] for code in codes) / 1000)
    return label, f"{thousands}k" if thousands else "<1k"


def build_forecast(document, cycle, now):
    blocks = parse_bulletin(document, cycle)
    start = first_valid(cycle)
    station_data = [blocks[station] for station in STATIONS]

    def values(key, column):
        return [block[key][column] for block in station_data]

    rows = []
    for offset in range(HORIZON):

        temp = average([numeric(value, -98, 150) for value in values("TMP", offset)])
        dewpoint = average([numeric(value, -98, 100) for value in values("DPT", offset)])
        speed, direction = wind(
            [numeric(value, 0, 98) for value in values("WSP", offset)],
            [numeric(value, 1, 36) for value in values("WDR", offset)],
        )
        cover, ceiling = clouds(values("CLD", offset), [numeric(value, 1, 8) for value in values("CIG", offset)])
        # P01 is indexed by the interval end; conditions are indexed by its start.
        precip = average([numeric(value, 0, 100) for value in values("P01", offset + 1)])
        valid = start + offset * MODEL_HOUR
        rows.append({
            "time": iso(valid), "endTime": iso(valid + MODEL_HOUR), "tempF": nearest(temp),
            "dewpointF": nearest(dewpoint), "windMph": speed, "windDirection": direction,
            "cloudCover": cover, "ceiling": ceiling, "precipChance": nearest(precip),
        })
    if any(all(row[field] is None for row in rows) for field in
           ("tempF", "dewpointF", "windMph", "cloudCover", "precipChance")):
        raise ValueError("LAMP bulletin is missing a forecast field for the entire window")
    return {"cycle": iso(cycle), "checkedAt": iso(now), "rows": rows}


def fetch_forecast(download, cycle, now):
    return build_forecast(download(bulletin_url(cycle)).decode("ascii", errors="replace"), cycle, now)


def fetch_initial_forecast(download, cycle, now):
    try:
        return fetch_forecast(download, cycle, now)
    except (HTTPError, URLError, TimeoutError, ValueError):
        return fetch_forecast(download, cycle - MODEL_HOUR, now)
