"""Cloud Run Job entry point. A failed collection never overwrites the last good blend."""
import argparse
from datetime import datetime, timezone
import logging
import time
from forecast_models import target_cycle, locate, collect_model, blend
from forecast_store import read_forecast, write_forecast


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
    try:
        old = read_forecast()
        if old["cycle"] >= cycle.isoformat().replace("+00:00", "Z"):
            logging.info("Cycle already published; skipping downloads")
            return
    except FileNotFoundError:
        pass
    # Check both f018 indexes first. Don't spend minutes downloading half a blend.
    located = {model: locate(model, cycle) for model in ("HRRR", "RRFS")}
    data = {model: collect_model(model, cycle, located[model]) for model in located}
    sources = {model: {"url": located[model][0], "feed": "parallel" if "/para/" in located[model][0] else "operational"} for model in located}
    forecast = blend(data, cycle, sources)
    forecast["processingSeconds"] = round(time.monotonic() - started, 1)
    write_forecast(forecast)
    logging.info("Published %s: 17 timestamps, 16 hours, 6 contributors; %.1f seconds", forecast["cycle"], forecast["processingSeconds"])


if __name__ == "__main__":
    main()
