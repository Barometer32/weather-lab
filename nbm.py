"""Read NOAA’s operational National Blend of Models station guidance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

STATION = "KFCM"
KEY = "live/nbm-kfcm.json"
ARCHIVE = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
HEADER = re.compile(rb"^\s*KFCM\s+NBM\s+(?:V[\d.]+\s+)?(NB[HSEX]) GUIDANCE\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{4}) UTC\s*$")
FIELDS = {
    "TMP": ("temperatureF", -100, 160),
    "DPT": ("dewPointF", -100, 120),
    "SKY": ("cloudCoverPct", 0, 100),
    "WDR": ("windDirectionTens", 0, 36),
    "WSP": ("windKnots", 0, 200),
    "GST": ("gustKnots", 0, 200),
    "P01": ("precipChancePct", 0, 100),
    "Q01": ("liquidPrecipHundredths", 0, 999),
    "S01": ("snowTenths", 0, 999),
    "PRA": ("rainTypePct", 0, 100),
    "PSN": ("snowTypePct", 0, 100),
    "PZR": ("iceTypePct", 0, 100),
    "PPL": ("sleetTypePct", 0, 100),
}


def bulletin_url(cycle, product="NBH"):
    return f"{ARCHIVE}/blend.{cycle:%Y%m%d}/{cycle:%H}/text/blend_{product.lower()}tx.t{cycle:%H}z"


def station_lines(lines, cycle, product):
    found = False
    for raw in lines:
        line = raw.rstrip(b"\r\n")
        if not found:
            match = HEADER.fullmatch(line)
            if not match or match[1] != product.encode():
                continue
            stamp = datetime.strptime(b" ".join(match.groups()[1:]).decode(), "%m/%d/%Y %H%M").replace(tzinfo=timezone.utc)
            if stamp != cycle:
                raise ValueError("NBM station card cycle does not match its object name")
            found = True
            continue
        if not line.strip() or b"GUIDANCE" in line:
            break
        yield line[:4].strip().decode("ascii", errors="ignore"), line


def number(token, low, high):
    token = token.strip()
    value = int(token) if re.fullmatch(rb"-?\d{1,3}", token) else None
    return value if value is not None and value not in (-88, -99) and low <= value <= high else None


def parse_station(lines, cycle):
    fields = {label: [line[i:i+3].strip() for i in range(5, len(line.rstrip()) if label == "UTC" else len(line), 3)]
              for label, line in station_lines(lines, cycle, "NBH") if label == "UTC" or label in FIELDS}
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
            row[name] = number(token, low, high)
        result.append(row)
    if not any(row["temperatureF"] is not None for row in result):
        raise ValueError("NBM station card has no temperatures")
    return result


def read_bulletin(cycle, product="NBH"):
    request = Request(bulletin_url(cycle, product), headers={"User-Agent": "Weather Lab NBM/1.0"})
    with urlopen(request, timeout=15) as response:
        def bounded_lines():
            total = 0
            while line := response.readline(1024):
                total += len(line)
                if total > 40_000_000 or len(line) == 1024:
                    raise ValueError("NBM text bulletin exceeded expected size")
                yield line
        if product == "NBH":
            return parse_station(bounded_lines(), cycle)
        return parse_extended(bounded_lines(), cycle, product)


def collect(store, now, read=None):
    read = read or read_cycle
    previous = store.read_json(KEY) or {}
    latest = now.replace(minute=0, second=0, microsecond=0)
    if now.minute < 45:
        latest -= timedelta(hours=1)
    for offset in range(3):
        cycle = latest - timedelta(hours=offset)
        stamp = cycle.isoformat()
        if previous.get("cycleAt", "") >= stamp and previous.get("hours") and previous.get("days"):
            return {"status": "current bulletin retained", "cycleAt": previous["cycleAt"]}
        try:
            hours, days, horizon = read(cycle)
        except (URLError, TimeoutError, ValueError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (403, 404, 429, 500, 502, 503, 504):
                raise
            continue
        store.write_json(KEY, {"product": "NBH", "station": STATION, "cycleAt": stamp,
                               "checkedAt": now.isoformat(), "sourceUrl": bulletin_url(cycle), "hours": hours,
                               "days": days, "horizonHours": horizon})
        return {"status": "prepared", "cycleAt": stamp, "hours": len(hours), "days": len(days)}
    raise ValueError("No usable recent NOAA NBM bulletin; saved guidance was not replaced")


def parse_extended(lines, cycle, product):
    fields = {label: line.replace(b"|", b" ") for label, line in station_lines(lines, cycle, product)}
    if product == "NBS":
        width = 3
        ends = [i+width for i in range(5, len(fields.get("FHR", b"").rstrip()), width)]
        cadence = 3
        interval = 6
    else:
        # NBE/NBX numbers are right-aligned against FHR; vertical bars and
        # leading padding differ across products and cycles. CLIMO has no FHR.
        width = 4
        ends = [4+m.end() for m in re.finditer(rb"\d{1,3}", fields.get("FHR", b"")[4:])]
        cadence = interval = 12

    def field(label, end, low, high):
        return number(fields.get(label, b"")[end-width:end], low, high)

    rows = []
    for end in ends:
        hour = field("FHR", end, 1, 264)
        if hour is None or (rows and hour != rows[-1]["leadHour"] + cadence):
            raise ValueError(f"Invalid {product} forecast hours")
        valid = cycle + timedelta(hours=hour)
        raw_utc = fields.get("UTC", b"")[end-width:end].strip()
        if not raw_utc.isdigit() or int(raw_utc) != valid.hour:
            raise ValueError(f"Invalid {product} UTC alignment")
        rows.append({
            "validAt": valid.isoformat(), "leadHour": hour, "interval": interval,
            "extremeF": field("TXN", end, -100, 160), "cloudCoverPct": field("SKY", end, 0, 100),
            "precipChancePct": field(f"P{interval:02}", end, 0, 100),
            "liquidPrecipHundredths": field(f"Q{interval:02}", end, 0, 999),
            "snowTenths": field(f"S{interval:02}", end, 0, 999),
            "rainTypePct": field("PRA", end, 0, 100), "snowTypePct": field("PSN", end, 0, 100),
            "iceTypePct": field("PZR", end, 0, 100), "sleetTypePct": field("PPL", end, 0, 100),
        })
    if len(rows) < {"NBS": 18, "NBE": 12, "NBX": 5}[product]:
        raise ValueError(f"Incomplete {product} station card")
    return rows


def daily_outlook(cycle, hourly, short, extended):
    """Summarize a NOAA day and following night, from 12 UTC to 12 UTC."""
    times = {}
    for interval, rows in ((1, hourly), (6, short), (12, extended)):
        for row in rows:
            times.setdefault(datetime.fromisoformat(row["validAt"]), {})[interval] = row
    latest = datetime.fromisoformat(extended[-1]["validAt"])
    first = cycle.replace(hour=12)
    if first > cycle:
        first -= timedelta(days=1)

    def pick(end, key):
        return next((row[key] for _, row in sorted(times.get(end, {}).items(), reverse=True)
                     if row.get(key) is not None), None)

    def total(start, end, key):
        # Find a continuous cover of the requested span, preferring the longest
        # NOAA interval at each step. Missing accumulation is never treated as zero.
        sums = {start: 0}
        cursor = start + timedelta(hours=1)
        while cursor <= end:
            for width, row in sorted(times.get(cursor, {}).items(), reverse=True):
                previous = cursor - timedelta(hours=width)
                if previous in sums and row.get(key) is not None:
                    sums[cursor] = sums[previous] + row[key]
                    break
            cursor += timedelta(hours=1)
        return sums.get(end)

    days = []
    while first < latest:
        night_end = first + timedelta(days=1)
        evening = first + timedelta(hours=12)
        start, end = max(first, cycle), min(night_end, latest)
        if start >= end:
            first = night_end
            continue
        # Use the bulletin’s forecast max/min rather than extrema of sampled temperatures.
        high = pick(evening, "extremeF") if evening > cycle else None
        low = pick(night_end, "extremeF")
        def hourly_extreme(left, right, extreme):
            samples = [times.get(left + timedelta(hours=i), {}).get(1, {}).get("temperatureF")
                       for i in range(1, int((right-left).total_seconds()//3600)+1)]
            return extreme(samples) if samples and all(value is not None for value in samples) else None

        high_hourly = low_hourly = False
        if high is None and start < evening <= end:
            high = hourly_extreme(start, evening, max)
            high_hourly = high is not None
        if low is None and end == night_end:
            low = hourly_extreme(max(start, evening), end, min)
            low_hourly = low is not None
        cloud = pick(evening, "cloudCoverPct") if evening > cycle else None
        # Pick 12-hour PoPs where available, falling back to shorter periods
        # only for an uncovered half-day. PoPs cannot be summed.
        chances, types = [], set()
        for half in (evening, night_end):
            left, right = max(start, half - timedelta(hours=12)), min(end, half)
            if left >= right:
                continue
            complete = left == half - timedelta(hours=12) and right == half
            full = times.get(half, {}).get(12) if complete else None
            if full and full.get("precipChancePct") is not None:
                candidates = [full]
            else:
                candidates = [row for valid, by_width in times.items() if left < valid <= right
                              for width, row in by_width.items()
                              if width < 12 and valid - timedelta(hours=width) >= left
                              and row.get("precipChancePct") is not None]
            chances.extend(row["precipChancePct"] for row in candidates)
            for row in candidates:
                if row["precipChancePct"] >= 20:
                    types.update(label for label, key in (
                        ("rain", "rainTypePct"), ("snow", "snowTypePct"),
                        ("ice", "iceTypePct"), ("sleet", "sleetTypePct")) if (row.get(key) or 0) >= 25)
        liquid, snow = (total(start, end, key) for key in ("liquidPrecipHundredths", "snowTenths"))
        if snow:
            types.add("snow")
        days.append({
            "date": first.date().isoformat(), "startAt": start.isoformat(), "endAt": end.isoformat(),
            "partial": start != first or end != night_end,
            "highF": high, "highFromHourly": high_hourly, "lowF": low, "lowFromHourly": low_hourly, "eveningCloudPct": cloud,
            "peakPrecipChancePct": max(chances, default=None),
            "liquidPrecipHundredths": liquid, "snowTenths": snow,
            "precipTypes": sorted(types),
        })
        first = night_end
    return days


def read_cycle(cycle, read=read_bulletin):
    with ThreadPoolExecutor(max_workers=4) as executor:
        hourly, short, extended, far = executor.map(
            lambda product: read(cycle, product), ("NBH", "NBS", "NBE", "NBX"))
    if far[0]["leadHour"] != extended[-1]["leadHour"] + 12 or far[-1]["leadHour"] < 250:
        raise ValueError("NBM station bulletins do not form a full outlook")
    return hourly, daily_outlook(cycle, hourly, short, extended+far), far[-1]["leadHour"]
