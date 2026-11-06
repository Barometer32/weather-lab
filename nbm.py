"""Read NOAA’s operational National Blend of Models station guidance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
import math
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

STATION = "KFCM"
KEY = "live/nbm-kfcm.json"
CENTRAL = ZoneInfo("America/Chicago")
OUTLOOK_VERSION = 3
PRECIP_TYPES = {"rain": "rainTypePct", "snow": "snowTypePct", "freezing rain": "iceTypePct", "sleet": "sleetTypePct"}
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
    "I01": ("iceHundredths", 0, 999),
    "T01": ("thunderPct", 0, 100),
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
        if previous.get("cycleAt", "") >= stamp and previous.get("hours") and previous.get("outlookVersion") == OUTLOOK_VERSION and previous.get("days"):
            return {"status": "current bulletin retained", "cycleAt": previous["cycleAt"]}
        try:
            hours, days, horizon = read(cycle)
        except (URLError, TimeoutError, ValueError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (403, 404, 429, 500, 502, 503, 504):
                raise
            continue
        store.write_json(KEY, {"product": "NBH", "station": STATION, "cycleAt": stamp,
                               "checkedAt": now.isoformat(), "sourceUrl": bulletin_url(cycle), "hours": hours,
                               "days": days, "horizonHours": horizon, "outlookVersion": OUTLOOK_VERSION})
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
            **{name: field(label, end, low, high) for label, (name, low, high) in FIELDS.items()
               if label not in {"P01", "Q01", "S01", "T01", "I01"}},
            "extremeF": field("TXN", end, -100, 160),
            "precip12Pct": field("P12", end, 0, 100), "liquid12Hundredths": field("Q12", end, 0, 999),
            "thunder12Pct": field("T12", end, 0, 100),
            "precipChancePct": field(f"P{interval:02}", end, 0, 100),
            "liquidPrecipHundredths": field(f"Q{interval:02}", end, 0, 999),
            "snowTenths": field(f"S{interval:02}", end, 0, 999),
            "thunderPct": field(f"T{interval:02}", end, 0, 100),
            "iceHundredths": field(f"I{interval:02}", end, 0, 999),
        })
    if len(rows) < {"NBS": 18, "NBE": 12, "NBX": 5}[product]:
        raise ValueError(f"Incomplete {product} station card")
    return rows


def sample_span(points, start, end):
    """Clip forecast samples to a window, interpolating its two boundaries."""
    if not points:
        return None

    def at(when):
        for i, (stamp, value) in enumerate(points):
            if stamp == when:
                return value
            if stamp > when:
                if not i:
                    return value if stamp - when <= timedelta(hours=1) else None
                before, earlier = points[i - 1]
                if stamp - before > timedelta(hours=12):
                    return None
                return earlier + (value - earlier) * ((when - before) / (stamp - before))
        return None

    first, last = at(start), at(end)
    if first is None or last is None:
        return None
    inside = [(stamp, v) for stamp, v in points if start < stamp < end]
    span = [(start, first), *inside, (end, last)]
    return span if all(b-a <= timedelta(hours=12) for (a, _), (b, _) in zip(span, span[1:])) else None


def sample_mean(span):
    if not span:
        return None
    weighted = sum((a + b) * (end - start).total_seconds() / 2
                   for (start, a), (end, b) in zip(span, span[1:]))
    return weighted / (span[-1][0] - span[0][0]).total_seconds()


def interval_cover(intervals, start, end, key, allow_shift=False):
    """Choose a full, nonoverlapping cover, preferring the least boundary spill."""
    best = {start: (0, 0, [])}
    for left, right, row in sorted(intervals, key=lambda item: item[1]):
        if row.get(key) is None or left >= end or right <= start:
            continue
        a, b = max(left, start), min(right, end)
        spill = (a-left + right-b).total_seconds()
        # At a clock offset, the edge may be a small portion of a long
        # interval (e.g. the last hour of the prior UTC half-day).
        if a not in best or (spill and (not allow_shift or min(spill, (b-a).total_seconds()) > 7200)):
            continue
        prev_spill, count, path = best[a]
        score = prev_spill + spill, count + 1
        if b not in best or score < best[b][:2]:
            best[b] = (*score, path + [(row, (b-a)/(right-left))])
    return best.get(end)


def daily_outlook(cycle, hourly, short, extended):
    """Group daytime highs and the following overnight lows by local date."""
    points = {}
    intervals = []
    for cadence, rows in ((12, extended), (3, short), (1, hourly)):
        for row in rows:
            stamp = datetime.fromisoformat(row["validAt"])
            fields = points.setdefault(stamp, {})
            fields.update({k: v for k, v in row.items() if v is not None})
            width = {1: 1, 3: 6, 12: 12}[cadence]
            intervals.append((stamp - timedelta(hours=width), stamp, row))
            if cadence == 3:
                intervals.append((stamp - timedelta(hours=12), stamp, {
                    "precipChancePct": row.get("precip12Pct"), "liquidPrecipHundredths": row.get("liquid12Hundredths"),
                    "thunderPct": row.get("thunder12Pct"), **{k: row.get(k) for k in PRECIP_TYPES.values()},
                }))

    series = {}
    for stamp, row in sorted(points.items()):
        for field, value in row.items():
            if isinstance(value, (int, float)):
                series.setdefault(field, []).append((stamp, value))
        speed, direction = row.get("windKnots"), row.get("windDirectionTens")
        if speed is not None and direction:
            theta = math.radians(direction*10)
            series.setdefault("windEast", []).append((stamp, speed * math.sin(theta)))
            series.setdefault("windNorth", []).append((stamp, speed * math.cos(theta)))
        elif speed == 0:
            for field in ("windEast", "windNorth"):
                series.setdefault(field, []).append((stamp, 0))

    def round_value(value):
        return None if value is None else round(value)

    def period(start, end, name, extreme_at):
        if start < cycle < end:
            start = cycle

        def span(field):
            return sample_span(series.get(field, []), start, end)

        def average(field):
            return sample_mean(span(field))

        def limits(field):
            values = span(field)
            return (round(min(v for _, v in values)), round(max(v for _, v in values))) if values else (None, None)

        def accumulation(key):
            cover = interval_cover(intervals, start, end, key, allow_shift=True)
            if cover is None:
                return None, False
            total = round(sum(row[key] * fraction for row, fraction in cover[2]))
            return total, bool(cover[0] and any(row[key] and fraction < 1 for row, fraction in cover[2]))

        def chances(key):
            cover = interval_cover(intervals, start, end, key, allow_shift=True)
            inside = [row for a, b, row in intervals if start <= a and b <= end and row.get(key) is not None]
            if cover is None:
                return inside, bool(inside)
            return [row for row, _ in cover[2]] + inside, bool(cover[0])

        low, high = limits("temperatureF")
        # TXN at 00Z is the preceding day's high; TXN at 12Z is
        # the low for the night that just ended, not the upcoming night.
        extreme = points.get(extreme_at, {}).get("extremeF")
        temperature = (low if name == "night" else high) if extreme is None else extreme
        cloud_low, cloud_high = limits("cloudCoverPct")
        _, gust = limits("gustKnots")
        cloud_series = series.get("cloudCoverPct", [])
        step = (end-start)/4
        cloud_blocks = [round_value(sample_mean(sample_span(cloud_series, start+i*step, start+(i+1)*step))) for i in range(4)]
        sparse = any(b - a > timedelta(hours=3) for field in ("cloudCoverPct", "temperatureF")
                     for (a, _), (b, _) in zip(series.get(field, []), series.get(field, [])[1:])
                     if a < end and b > start)
        speed = average("windKnots")
        east, north = average("windEast"), average("windNorth")
        direction = None if east is None or north is None or math.hypot(east, north) < 1 else round(math.degrees(math.atan2(east, north))) % 360
        pop, pop_shift = chances("precipChancePct")
        thunder, _ = chances("thunderPct")
        types = {label for row in pop if row["precipChancePct"] >= 20
                 for label, key in PRECIP_TYPES.items() if (row.get(key) or 0) >= 25}
        liquid, liquid_shift = accumulation("liquidPrecipHundredths")
        snow, snow_shift = accumulation("snowTenths")
        ice, ice_shift = accumulation("iceHundredths")
        if snow:
            types.add("snow")
        if ice:
            types.add("freezing rain")
        return {
            "kind": name, "startAt": start.isoformat(), "endAt": end.isoformat(), "sparse": sparse,
            "highF": temperature if name == "day" else None,
            "lowF": temperature if name == "night" else None,
            "temperatureSource": "bulletin" if extreme is not None else "sampled",
            "cloudPct": round_value(average("cloudCoverPct")),
            "cloudMinPct": cloud_low, "cloudMaxPct": cloud_high, "cloudBlocks": cloud_blocks,
            "dewPointF": round_value(average("dewPointF")), "windKnots": round_value(speed),
            "windDirectionDegrees": direction, "gustKnots": gust,
            "peakPrecipChancePct": max((row["precipChancePct"] for row in pop), default=None),
            "precipChanceApproximate": pop_shift, "thunderPct": max((row["thunderPct"] for row in thunder), default=None),
            "liquidPrecipHundredths": liquid, "snowTenths": snow, "iceHundredths": ice,
            "amountsApproximate": liquid_shift or snow_shift or ice_shift, "precipTypes": sorted(types),
        }

    latest = datetime.fromisoformat(extended[-1]["validAt"])
    local = cycle.astimezone(CENTRAL)
    date = local.date() - timedelta(days=local.hour < 6)
    days = []
    while len(days) < 10:
        start = datetime.combine(date, time(6), CENTRAL).astimezone(timezone.utc)
        evening = datetime.combine(date, time(18), CENTRAL).astimezone(timezone.utc)
        end = datetime.combine(date + timedelta(days=1), time(6), CENTRAL).astimezone(timezone.utc)
        if end > latest:
            break
        if end > cycle:
            next_date = date + timedelta(days=1)
            high_at = datetime.combine(next_date, time(0), timezone.utc)
            low_at = datetime.combine(next_date, time(12), timezone.utc)
            days.append({"date": date.isoformat(), "startAt": start.isoformat(), "endAt": end.isoformat(),
                         "periods": [period(start, evening, "day", high_at),
                                     period(evening, end, "night", low_at)]})
        date += timedelta(days=1)
    return days


def read_cycle(cycle, read=read_bulletin):
    with ThreadPoolExecutor(max_workers=4) as executor:
        hourly, short, extended, far = executor.map(
            lambda product: read(cycle, product), ("NBH", "NBS", "NBE", "NBX"))
    if far[0]["leadHour"] != extended[-1]["leadHour"] + 12 or far[-1]["leadHour"] < 250:
        raise ValueError("NBM station bulletins do not form a full outlook")
    return hourly, daily_outlook(cycle, hourly, short, extended+far), far[-1]["leadHour"]
