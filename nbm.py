"""Read NOAA's operational hourly National Blend of Models station guidance."""
from datetime import datetime, timedelta, timezone
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

STATION = "KFCM"
KEY = "live/nbm-kfcm.json"
ARCHIVE = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
HEADER = re.compile(rb"^\s*KFCM\s+NBM\s+(?:V[\d.]+\s+)?NBH GUIDANCE\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{4}) UTC\s*$")
FIELDS = {
    "TMP": ("temperatureF", -100, 160),
    "DPT": ("dewPointF", -100, 120),
    "SKY": ("cloudCoverPct", 0, 100),
    "WDR": ("windDirectionTens", 0, 36),
    "WSP": ("windKnots", 0, 200),
    "GST": ("gustKnots", 0, 200),
    "P01": ("precipChancePct", 0, 100),
    "Q01": ("liquidPrecipHundredths", 0, 999),
}


def bulletin_url(cycle):
    return f"{ARCHIVE}/blend.{cycle:%Y%m%d}/{cycle:%H}/text/blend_nbhtx.t{cycle:%H}z"


def parse_station(lines, cycle):
    fields = {}
    found = False
    for raw in lines:
        if not found:
            match = HEADER.fullmatch(raw.rstrip(b"\r\n"))
            if not match:
                continue
            stamp = datetime.strptime(b" ".join(match.groups()).decode(), "%m/%d/%Y %H%M").replace(tzinfo=timezone.utc)
            if stamp != cycle:
                raise ValueError("NBM station card cycle does not match its object name")
            found = True
            continue
        line = raw.rstrip(b"\r\n")
        if not line.strip() or b"NBH GUIDANCE" in line:
            break
        label = line[:4].strip().decode("ascii", errors="ignore")
        if label == "UTC" or label in FIELDS:
            if label == "UTC":
                line = line.rstrip()
            # One separator after the four-character label, then three bytes per hour.
            # Splitting on whitespace would lose missing columns and glued values.
            fields[label] = [line[i:i+3].strip() for i in range(5, len(line), 3)]
    hours = fields.get("UTC", [])
    if not 18 <= len(hours) <= 25 or "TMP" not in fields:
        raise ValueError("Incomplete KFCM NBM hourly station card")
    result = []
    for index, hour in enumerate(hours):
        valid = cycle + timedelta(hours=index+1)
        if hour != f"{valid:%H}".encode():
            raise ValueError("NBM hourly guidance did not have contiguous valid times")
        row = {"validAt": valid.isoformat()}
        for field, (name, low, high) in FIELDS.items():
            values = fields.get(field, [])
            token = values[index] if index < len(values) else b""
            value = int(token) if re.fullmatch(rb"-?\d{1,3}", token) else None
            row[name] = value if value is not None and value not in (-88, -99) and low <= value <= high else None
        result.append(row)
    if not any(row["temperatureF"] is not None for row in result):
        raise ValueError("NBM station card has no temperatures")
    return result


def read_bulletin(cycle):
    request = Request(bulletin_url(cycle), headers={"User-Agent": "Weather Lab NBM/1.0"})
    with urlopen(request, timeout=15) as response:
        def bounded_lines():
            total = 0
            while line := response.readline(1024):
                total += len(line)
                if total > 40_000_000 or len(line) == 1024:
                    raise ValueError("NBM text bulletin exceeded expected size")
                yield line
        return parse_station(bounded_lines(), cycle)


def collect(store, now, read=read_bulletin):
    previous = store.read_json(KEY) or {}
    latest = now.replace(minute=0, second=0, microsecond=0)
    if now.minute < 45:
        latest -= timedelta(hours=1)
    for offset in range(3):
        cycle = latest - timedelta(hours=offset)
        stamp = cycle.isoformat()
        if previous.get("cycleAt", "") >= stamp and previous.get("hours"):
            return {"status": "current bulletin retained", "cycleAt": previous["cycleAt"]}
        try:
            hours = read(cycle)
        except (URLError, TimeoutError, ValueError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (403, 404, 429, 500, 502, 503, 504):
                raise
            continue
        store.write_json(KEY, {"product": "NBH", "station": STATION, "cycleAt": stamp,
                               "checkedAt": now.isoformat(), "sourceUrl": bulletin_url(cycle), "hours": hours})
        return {"status": "prepared", "cycleAt": stamp, "hours": len(hours)}
    raise ValueError("No usable recent NOAA NBM bulletin; saved guidance was not replaced")
