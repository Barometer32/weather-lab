"""Official NWS day/night forecast for Hopkins."""
from datetime import datetime, timedelta, timezone
from html import unescape
import math
import re
from zoneinfo import ZoneInfo

LATITUDE, LONGITUDE = 44.9244, -93.4140
SOURCE_URL = ("https://forecast.weather.gov/MapClick.php?lat=44.9244&lon=-93.414"
              "&unit=0&lg=english&FcstType=text&TextType=1")
FORECAST_URL = ("https://forecast.weather.gov/MapClick.php?lat=44.9244&lon=-93.414"
                "&unit=0&lg=english&FcstType=json")
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


def text_forecast_only(data, periods):
    """Discard hourly fields that may still be present in older snapshots."""
    retired_fields = {"hourly", "hourlyUpdatedAt", "gridUpdatedAt", "hourlySourceUrl", "gridSourceUrl", "lamp"}
    result = {key: value for key, value in data.items() if key not in retired_fields}
    result["periods"] = [
        {key: value for key, value in period.items() if key not in ("hourlyWindows", "precipAmounts")}
        for period in periods
    ]
    return result


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
        falling = re.search(r"\btemperatures?\s+falling\s+to\s+(?:around\s+|near\s+)?(-?\d+)\b(?:\s+by\s+([^.,]+))?", text, re.I)
        periods.append({"name": name, "startTime": start.isoformat(), "endTime": end.isoformat(),
                        "isDaytime": label == "High", "temperature": number(temperature, -150, 150),
                        "temperatureUnit": "F", "shortForecast": summary[i] if i < len(summary) else None,
                        "detailedForecast": text.strip(), "precipChancePct": number(pop[i], 0, 100) if i < len(pop) else None})
        if falling:
            periods[-1].update(temperature=number(falling[1], -150, 150), temperatureTrend="falling",
                               trendTargetTime=falling[2].strip() if falling[2] else None)
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
