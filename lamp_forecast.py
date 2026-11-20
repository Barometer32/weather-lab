"""Three-airport hourly guidance from the NOAA station LAMP bulletin."""
from datetime import datetime, timedelta, timezone
from math import floor
import re
from statistics import mean

from app import wind_mean

STATIONS = ("KMSP", "KFCM", "KMIC")
SOURCE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/lmp/prod"
HOUR = timedelta(hours=1)
HEADER = re.compile(r"^\s*([A-Z0-9]{4}) +GFS LAMP GUIDANCE +(\d+/\d+/\d{4}) +(\d{4}) UTC")
FIELDS = ("UTC", "TMP", "DPT", "WDR", "WSP", "P01", "CLD", "CIG")
# Category midpoints in oktas. LAMP does not report exact cloud percentages.
SKY = {"CL": (0, "Clear"), "FW": (1, "Few clouds"), "SC": (3, "Scattered"),
       "BK": (6, "Broken"), "OV": (8, "Overcast")}
CEILING_MIDPOINT_FT = (100, 300, 700, 1450, 2500, 4800, 9300)
OPEN_CEILING_FT = 12000
VERSION = 2


def bulletin_url(cycle):
    return f"{SOURCE}/lmp.{cycle:%Y%m%d}/lmp.t{cycle:%H%M}z.lavtxt.ascii"


def station_columns(bulletin, cycle):
    stations = {}
    fields = None
    for line in bulletin.decode("ascii", errors="replace").splitlines():
        header = HEADER.match(line)
        if header:
            station, date, hour = header.groups()
            fields = None
            if station in STATIONS:
                issued = datetime.strptime(f"{date} {hour}", "%m/%d/%Y %H%M").replace(tzinfo=timezone.utc)
                if issued != cycle or station in stations:
                    raise ValueError("Unexpected LAMP station bulletin cycle")
                fields = stations[station] = {}
        elif fields is not None and line[:4].strip() in FIELDS:
            # The field name occupies four characters, followed by one spacer
            # and three characters per hour. Splitting on whitespace joins
            # consecutive 100% probabilities (and loses missing columns).
            fields[line[:4].strip()] = [line[i:i+3].strip() for i in range(5, 80, 3)]
    expected_hours = [f"{cycle+HOUR*i:%H}" for i in range(1, 26)]
    for station in STATIONS:
        rows = stations.get(station, {})
        if rows.get("UTC") != expected_hours or any(len(rows.get(key, ())) != 25 for key in FIELDS):
            raise ValueError(f"Incomplete LAMP bulletin for {station}")
    return stations


def integer(value, low, high):
    try:
        number = int(value)
    except ValueError:
        return None
    return number if low <= number <= high else None


def all_station_mean(values):
    return mean(values) if None not in values else None


def ceiling_text(categories):
    if None in categories:
        return None
    estimate = mean(CEILING_MIDPOINT_FT[code-1] if code < 8 else OPEN_CEILING_FT for code in categories)
    if 8 in categories:
        # The top bin is open-ended. Its lower edge gives a bound on the
        # midpoint estimate; rounding down preserves that bound in the label.
        return f">{floor(estimate / 100) / 10:g}k"
    if estimate < 1000:
        return f"{round(estimate / 100) * 100} ft"
    thousands = estimate / 1000
    return f"{round(thousands, 1) if thousands < 5 else round(thousands):g}k"


def parse_bulletin(bulletin, cycle):
    stations = station_columns(bulletin, cycle)
    hours = []
    for i in range(24):
        values = {key: [station[key][i] for station in stations.values()] for key in FIELDS if key != "P01"}
        temp = all_station_mean([integer(v, -100, 150) for v in values["TMP"]])
        dewpoint = all_station_mean([integer(v, -100, 100) for v in values["DPT"]])
        reports = []
        for speed, direction in zip(values["WSP"], values["WDR"]):
            speed_knots = integer(speed, 0, 98)
            bearing = integer(direction, 1, 36)
            reports.append({"wspd": speed_knots, "wdir": bearing*10 if bearing is not None else None})
        wind = wind_mean(reports)
        sky = [SKY.get(v, (None, None))[0] for v in values["CLD"]]
        cover = all_station_mean(sky)
        ceilings = [integer(v, 1, 8) for v in values["CIG"]]
        ceiling = ceiling_text(ceilings)
        start = cycle.replace(minute=0) + HOUR*(i+1)
        # P01 in the following column ends at the end of this row's hour.
        chance = all_station_mean([integer(s["P01"][i+1], 0, 100) for s in stations.values()])
        hours.append({
            "startTime": start.isoformat(), "endTime": (start+HOUR).isoformat(),
            "temperatureF": temp, "dewpointF": dewpoint,
            "windMph": wind["speedMph"] if wind["speedCount"] == 3 else None,
            "windDirection": wind["direction"] if wind["speedCount"] == 3 else None,
            "skyCover": min(SKY.values(), key=lambda item: abs(item[0]-cover))[1] if cover is not None else None,
            "ceiling": ceiling, "precipChancePct": chance,
        })
    if not any(row["temperatureF"] is not None for row in hours):
        raise ValueError("No complete three-station LAMP temperatures")
    return {"version": VERSION, "cycleTime": cycle.isoformat(), "stations": list(STATIONS), "hours": hours}


def refresh_lamp(previous, download, now):
    now = now.astimezone(timezone.utc)
    cycle = now.replace(minute=30, second=0, microsecond=0)
    if cycle > now:
        cycle -= HOUR
    current_format = previous and previous.get("version") == VERSION
    if current_format and previous["cycleTime"] >= cycle.isoformat():
        return previous
    # Once a run is prepared, retry only the new cycle on the next scheduled
    # check. At cold start, the prior cycle can fill the initial release gap.
    try:
        return parse_bulletin(download(bulletin_url(cycle)), cycle)
    except (OSError, ValueError):
        usable_previous = previous and datetime.fromisoformat(previous["hours"][-1]["endTime"]) > now
        if current_format and usable_previous:
            return previous
        prior = cycle-HOUR
        try:
            return parse_bulletin(download(bulletin_url(prior)), prior)
        except (OSError, ValueError):
            if usable_previous:
                return previous
            raise
