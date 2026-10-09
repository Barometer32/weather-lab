"""Present the official NWS MapClick forecast without rewriting its narrative."""
from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo

LATITUDE, LONGITUDE = 44.9244, -93.4140
SOURCE_URL = ("https://forecast.weather.gov/MapClick.php?lat=44.9244&lon=-93.414"
              "&unit=0&lg=english&FcstType=text&TextType=1")
FORECAST_URL = ("https://forecast.weather.gov/MapClick.php?lat=44.9244&lon=-93.414"
                "&unit=0&lg=english&FcstType=json")
FORECAST_VERSION = "nws-mapclick-v1"
CENTRAL = ZoneInfo("America/Chicago")


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
