"""Present the official NWS MapClick forecast without rewriting its narrative."""
from datetime import datetime, timedelta, timezone
from html import unescape
import math
import re
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

LATITUDE, LONGITUDE = 44.9244, -93.4140
SOURCE_URL = ("https://forecast.weather.gov/MapClick.php?lat=44.9244&lon=-93.414"
              "&unit=0&lg=english&FcstType=text&TextType=1")
FORECAST_URL = ("https://forecast.weather.gov/MapClick.php?lat=44.9244&lon=-93.414"
                "&unit=0&lg=english&FcstType=json")
POINT_URL = f"https://api.weather.gov/points/{LATITUDE:.4f},{LONGITUDE:.4f}"
FORECAST_VERSION = "nws-mapclick-v1"
CENTRAL = ZoneInfo("America/Chicago")
TEXT_FEED = "nws-mapclick-text"
JSON_FEED = "nws-mapclick-json"


def timestamp(value):
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("NWS forecast timestamp has no timezone")
    return moment


def number(value, minimum, maximum):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and minimum <= value <= maximum else None


def current_periods(periods, now):
    # Recheck saved periods at request time as well as at collection time.
    return [period for period in periods if timestamp(period["endTime"]) > now]


def normalize_forecast(document, now=None):
    now = now or datetime.now(timezone.utc)
    timing, data = document["time"], document["data"]
    names, starts, labels = (timing[key] for key in ("startPeriodName", "startValidTime", "tempLabel"))
    temperatures, narratives = (data[key] for key in ("temperature", "text"))
    required = (names, starts, labels, temperatures, narratives)
    if not all(isinstance(values, list) for values in required) or not names or any(len(values) != len(names) for values in required):
        raise ValueError("NWS MapClick returned incomplete or misaligned forecast periods")
    issued = timestamp(document["creationDate"])
    start_times = [timestamp(value) for value in starts]
    if any(right <= left for left, right in zip(start_times, start_times[1:])):
        raise ValueError("NWS forecast periods are not chronological")
    periods = []
    for i, (name, start, label, temperature, text) in enumerate(zip(names, start_times, labels, temperatures, narratives)):
        if label not in ("High", "Low") or not isinstance(name, str) or not name.strip() or not isinstance(text, str) or not text.strip():
            raise ValueError("NWS forecast period is missing its label or narrative")
        # MapClick supplies period starts. The following start closes each period;
        # the final standard day/night period ends 12 local hours later (DST aware).
        end = start_times[i+1] if i+1 < len(start_times) else start.astimezone(CENTRAL) + timedelta(hours=12)
        pop = data.get("pop", [])
        summary = data.get("weather", [])
        periods.append({"name": name, "startTime": start.isoformat(), "endTime": end.isoformat(),
                        "isDaytime": label == "High", "temperature": number(temperature, -150, 150),
                        "temperatureUnit": "F", "shortForecast": summary[i] if i < len(summary) else None,
                        "detailedForecast": text.strip(), "precipChancePct": number(pop[i], 0, 100) if i < len(pop) else None})
    periods = current_periods(periods, now)
    if not periods:
        raise ValueError("NWS returned no current or future forecast periods")
    return {"source": "National Weather Service", "location": "Hopkins, MN",
            "latitude": LATITUDE, "longitude": LONGITUDE, "sourceUrl": SOURCE_URL,
            "forecastVersion": FORECAST_VERSION,
            # creationDateLocal belongs to the current observation, not the forecast.
            "updatedAt": issued.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "fetchedAt": now.isoformat().replace("+00:00", "Z"), "periods": periods}


def plain_text(markup):
    return " ".join(unescape(re.sub(r"<[^>]+>", "", markup)).split())


def is_daytime(name):
    return not re.search(r"\b(?:night|tonight|overnight|evening)\b", name, re.I)


def text_period_start(name, issued):
    # MapClick text has period names but no boundaries. Use the named local
    # day/night windows to expire saved text; keep the NWS name verbatim.
    day = is_daytime(name)
    anchor = issued.replace(hour=6 if day else 18, minute=0, second=0, microsecond=0)
    weekday = re.match(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", name, re.I)
    if weekday:
        if not day and issued.hour < 6 and (anchor-timedelta(days=1)).strftime("%A").lower() == weekday[0].lower():
            return anchor-timedelta(days=1)
        return next(anchor + timedelta(days=i) for i in range(7)
                    if (anchor + timedelta(days=i)).strftime("%A").lower() == weekday[0].lower())
    if not day and issued.hour < 6 and re.search(r"\b(?:overnight|rest of tonight)\b", name, re.I):
        return anchor-timedelta(days=1)
    return anchor


def normalize_text_forecast(html, now):
    # Extract only the forecast cell that follows the Hopkins issuance, not
    # other bold labels (e.g. advisories or footer links).
    match = re.search(r"NWS Forecast for:\s*Hopkins\s+MN\s*</b>.*?"
                      r"Last Update:\s*</b>\s*</a>\s*([^<]+)</td>.*?"
                      r"</table>\s*<table\b[^>]*>\s*<tr\b[^>]*>\s*<td\b[^>]*>(.*?)</td>",
                      html, re.I | re.S)
    if not match:
        raise ValueError("NWS text page did not contain the Hopkins forecast")
    issued_match = re.fullmatch(r"(\d{1,2}:\d{2}\s*[AP]M)\s+(CST|CDT)\s+(.+)", plain_text(match[1]), re.I)
    if not issued_match:
        raise ValueError("NWS text page did not provide an issuance time")
    stamp, zone, date = issued_match.groups()
    offset = {"CST": -6, "CDT": -5}[zone.upper()]
    issued = datetime.strptime(f"{stamp.upper()} {date}", "%I:%M %p %b %d, %Y")
    issued = issued.replace(tzinfo=timezone(timedelta(hours=offset))).astimezone(CENTRAL)
    rows = re.findall(r"<b\b[^>]*>([^<]+):\s*</b>(.*?)<br\s*/?>", match[2], re.I | re.S)
    if not rows:
        raise ValueError("NWS text page did not provide forecast periods")
    start = text_period_start(plain_text(rows[0][0]), issued)
    names, starts, labels, temperatures, narratives = [], [], [], [], []
    for label, narrative in rows:
        name, narrative = plain_text(label), plain_text(narrative)
        day = is_daytime(name)
        if not name or not narrative or day != (start.hour == 6):
            raise ValueError("NWS text forecast periods did not alternate day and night")
        kind = "high" if day else "low"
        temp = re.search(rf"\b{kind}\s+(?:near|around|of)\s+(-?\d+)\b", narrative, re.I)
        names.append(name)
        starts.append(start.isoformat())
        labels.append(kind.title())
        temperatures.append(temp[1] if temp else None)
        narratives.append(narrative)
        start += timedelta(hours=12)
    forecast = normalize_forecast(
        {"creationDate": issued.isoformat(),
         "time": {"startPeriodName": names, "startValidTime": starts, "tempLabel": labels},
         "data": {"temperature": temperatures, "text": narratives}}, now)
    forecast["forecastFeed"] = TEXT_FEED
    return forecast


def grid_end(start, duration):
    parts = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", duration)
    if not parts or not any(parts.groups()):
        raise ValueError("Invalid NWS weather interval")
    days, hours, minutes, seconds = (int(part or 0) for part in parts.groups())
    return start + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


WET_TYPES = {
    "freezing_rain": "freezing rain", "freezing_drizzle": "freezing drizzle",
    "rain": "rain", "rain_showers": "rain showers", "drizzle": "drizzle",
    "snow": "snow", "snow_showers": "snow showers", "sleet": "sleet",
    "thunderstorms": "thunderstorms", "hail": "hail",
}


def grid_weather(document):
    intervals = []
    for item in document.get("properties", {}).get("weather", {}).get("values", []):
        try:
            start_text, duration = item["validTime"].split("/", 1)
            start = timestamp(start_text).astimezone(timezone.utc)
            end = grid_end(start, duration)
            wet = [entry for entry in item["value"] if entry.get("weather") in WET_TYPES]
            if wet:
                intervals.append((start, end, wet))
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return intervals


def wet_description(start, end, intervals, condition):
    descriptions = []
    for left, right, entries in intervals:
        if not left <= start < end <= right:
            continue
        for entry in entries:
            kind = WET_TYPES[entry["weather"]]
            if not re.search(r"\b" + re.escape(kind.rstrip("s")) + r"s?\b", condition.lower()):
                continue
            coverage = entry.get("coverage")
            coverage = coverage.replace("_", " ") if isinstance(coverage, str) else ""
            intensity = entry.get("intensity")
            intensity = intensity.replace("_", " ") if intensity in ("very_light", "light", "moderate", "heavy") else ""
            wording = (f"{coverage} of {kind}" if coverage in ("chance", "slight chance", "areas", "periods")
                       else f"{kind} likely" if coverage == "likely"
                       else kind if coverage == "definite" else " ".join(filter(None, (coverage, kind))))
            descriptions.append(wording.capitalize() + (f" ({intensity})" if intensity else ""))
    return list(dict.fromkeys(descriptions))


def normalize_hourly(document, grid, now):
    props = document["properties"]
    issued = timestamp(props.get("updateTime") or props["generatedAt"])
    intervals = grid_weather(grid)
    # Only keep the first 48 hours; the regular NWS outlook continues beyond that.
    limit = now + timedelta(hours=48)
    hours = []
    for period in props["periods"]:
        try:
            start, end = (timestamp(period[k]).astimezone(timezone.utc) for k in ("startTime", "endTime"))
            condition = period["shortForecast"].strip()
            chance = number((period.get("probabilityOfPrecipitation") or {}).get("value"), 0, 100)
            if now < end and start < limit and end - start == timedelta(hours=1) and condition:
                hours.append((start, end, condition, chance, wet_description(start, end, intervals, condition)))
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    if not hours:
        raise ValueError("NWS hourly feed has no usable forecast hours")
    return issued.isoformat(), sorted({hour[0]: hour for hour in hours}.values())


def chance_band(chance):
    if chance is None:
        return None
    return sum(chance >= threshold for threshold in (15, 30, 60, 80))


def add_hourly_windows(forecast, hourly, grid, now):
    issued, hours = normalize_hourly(hourly, grid, now)
    forecast["hourlyUpdatedAt"] = issued
    for period in forecast["periods"]:
        left, right = (timestamp(period[k]) for k in ("startTime", "endTime"))
        windows = []
        for start, end, condition, chance, weather in hours:
            start, end = max(left, start), min(right, end)
            if start >= end:
                continue
            band = chance_band(chance)
            prior = windows[-1] if windows else None
            if (prior and timestamp(prior["endTime"]) == start and prior["condition"] == condition
                    and prior["weather"] == weather and chance_band(prior["maxChancePct"]) == band):
                prior["endTime"] = end.isoformat()
                if chance is not None:
                    prior["minChancePct"] = min(prior["minChancePct"], chance)
                    prior["maxChancePct"] = max(prior["maxChancePct"], chance)
            else:
                windows.append({"startTime": start.isoformat(), "endTime": end.isoformat(),
                                "condition": condition, "weather": weather,
                                "minChancePct": chance, "maxChancePct": chance})
        if windows:
            period["hourlyWindows"] = windows


def enrich_from_nws(forecast, fetch_json, now):
    props = fetch_json(POINT_URL)["properties"]
    hourly_url, grid_url = props["forecastHourly"], props["forecastGridData"]
    if not re.fullmatch(r"https://api\.weather\.gov/gridpoints/[A-Z]{3}/\d+,\d+", grid_url) or hourly_url != grid_url + "/forecast/hourly":
        raise ValueError("Unexpected NWS grid URLs")
    with ThreadPoolExecutor(max_workers=2) as pool:
        grid_work = pool.submit(fetch_json, grid_url)
        hourly_work = pool.submit(fetch_json, hourly_url)
        hourly = hourly_work.result()
        try:
            grid = grid_work.result()
        except (OSError, ValueError):
            grid = {}
    add_hourly_windows(forecast, hourly, grid, now)
