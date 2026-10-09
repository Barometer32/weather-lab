"""Cloud Run Job entry point. A failed collection never overwrites the last good blend."""
import argparse
from datetime import datetime, timedelta, timezone
import logging
import time
from forecast_models import target_cycle, locate, collect_model, blend, iso, ModelUnavailable, SCHEMA_VERSION
from forecast_store import read_forecast, write_forecast


def locate_common_cycle(target, published_cycle=None, lookback=3):
    """Prefer the scheduled cycle, then a newer-than-stored complete pair."""
    for age in range(lookback + 1):
        candidate = target - timedelta(hours=age)
        if published_cycle and iso(candidate) <= published_cycle:
            logging.info("No newer complete cycle found; keeping %s", published_cycle)
            return None
        try:
            located = {model: locate(model, candidate) for model in ("HRRR", "RRFS")}
        except ModelUnavailable as exc:
            logging.info("%s", exc)
            continue
        if age:
            logging.info("Preferred cycle %s is late; collecting complete common cycle %s", iso(target), iso(candidate))
        return candidate, located
    if published_cycle:
        logging.info("No newer complete cycle found; keeping %s", published_cycle)
        return None
    raise ModelUnavailable("No complete HRRR/RRFS pair available within the requested cycle window")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycle", help="Explicit UTC cycle, e.g. 2026-10-09T10:00:00Z")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    started = time.monotonic()
    cycle = datetime.fromisoformat(args.cycle.replace("Z", "+00:00")) if args.cycle else target_cycle(datetime.now(timezone.utc))
    if cycle.tzinfo is None or cycle.minute or cycle.second or cycle.microsecond:
        raise ValueError("Cycle must be a whole UTC hour with timezone")
    cycle = cycle.astimezone(timezone.utc)
    published_cycle = None
    try:
        old = read_forecast()
        published_cycle = old["cycle"]
        if old["cycle"] > iso(cycle) or (old["cycle"] == iso(cycle) and old.get("schemaVersion", 1) >= SCHEMA_VERSION):
            logging.info("Cycle already published; skipping downloads")
            return
        if old.get("schemaVersion", 1) < SCHEMA_VERSION:
            # Permit rebuilding the stored cycle once for the new wind/precip schema.
            published_cycle = iso(datetime.fromisoformat(old["cycle"].replace("Z", "+00:00")) - timedelta(hours=1))
    except FileNotFoundError:
        pass
    # Check both f018 indexes first. Don't spend minutes downloading half a blend.
    selected = locate_common_cycle(cycle, published_cycle, lookback=0 if args.cycle else 3)
    if selected is None:
        return
    cycle, located = selected
    data = {}
    for model in located:
        logging.info("Collecting %s %s forecast hours 1–18", model, iso(cycle))
        data[model] = collect_model(model, cycle, located[model])
    sources = {model: {"url": located[model][0], "feed": "parallel" if "/para/" in located[model][0] else "operational"} for model in located}
    forecast = blend(data, cycle, sources)
    forecast["processingSeconds"] = round(time.monotonic() - started, 1)
    write_forecast(forecast)
    logging.info("Published %s: 17 hourly intervals, 6 contributors; %.1f seconds", forecast["cycle"], forecast["processingSeconds"])


if __name__ == "__main__":
    main()
