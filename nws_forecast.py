"""Present the official NWS point forecast without modifying its forecast text."""
from datetime import datetime, timezone
import math

LATITUDE, LONGITUDE = 44.9244, -93.4140
POINT_URL = f"https://api.weather.gov/points/{LATITUDE},{LONGITUDE}"
SOURCE_URL = ("https://forecast.weather.gov/MapClick.php?lat=44.9244&lon=-93.414"
              "&unit=0&lg=english&FcstType=text&TextType=1")


def normalize_forecast(document, now=None):
    now = now or datetime.now(timezone.utc)
    properties = document["properties"]
    periods = []
    for period in properties.get("periods", []):
        # Keep an ongoing period, but never leave completed days on the page.
        end = datetime.fromisoformat(period["endTime"].replace("Z", "+00:00"))
        if end.tzinfo is None or end <= now:
            continue
        pop = (period.get("probabilityOfPrecipitation") or {}).get("value")
        if isinstance(pop, bool) or not isinstance(pop, (int, float)) or not math.isfinite(pop) or not 0 <= pop <= 100:
            pop = None
        periods.append({key: period.get(key) for key in (
            "name", "startTime", "endTime", "isDaytime", "temperature",
            "temperatureUnit", "temperatureTrend", "windSpeed", "windDirection",
            "shortForecast", "detailedForecast") } | {"precipChancePct": pop})
    if not periods:
        raise ValueError("NWS returned no current or future forecast periods")
    return {"source": "National Weather Service", "location": "Hopkins, MN",
            "latitude": LATITUDE, "longitude": LONGITUDE, "sourceUrl": SOURCE_URL,
            "updatedAt": properties.get("updateTime"),
            "fetchedAt": now.isoformat().replace("+00:00", "Z"), "periods": periods}
