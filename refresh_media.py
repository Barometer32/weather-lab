"""One-time data recovery with the collector identity; no public HTTP token."""
from datetime import datetime, timezone
import json
from native_radar import collect_site
from collector import collect_satellite, collect_forecast
from app import PALETTE
from realtime import get_store


def main():
    store=get_store()
    if store is None:
        raise ValueError("WEATHER_DATA_BUCKET is required")
    now=datetime.now(timezone.utc)
    print("Recovering the rolling two-hour KMPX archive", flush=True)
    result=collect_site(store,now,"KMPX",[{"dbz":v,"color":c} for v,c in PALETTE],budget=600)
    print(json.dumps({"radar":result}),flush=True)
    # Capture a fresh clock after the potentially longer archive recovery.
    print(json.dumps({"satellite":collect_satellite(store,datetime.now(timezone.utc))}),flush=True)
    print(json.dumps({"forecast":collect_forecast(store,datetime.now(timezone.utc))}),flush=True)


if __name__=="__main__":
    main()
