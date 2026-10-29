"""Read the public COD local GOES image loop; preserve RGB imagery unchanged."""
from datetime import datetime, timedelta, timezone
import re

FRAME_COUNT = 24
SECTOR = "S_Minnesota"
BASE = f"https://weather.cod.edu/wxdata/satellite/local/{SECTOR}"
PRODUCTS = {
    "13": {"label": "Infrared", "description": "GOES clean longwave infrared (Band 13), showing cloud-top brightness temperatures by day and night."},
    "truecolor": {"label": "True color", "description": "A natural daytime view of clouds and the ground. Requires sunlight; use NT Microphysics after dark."},
    "dcphase": {"label": "Day Cloud Phase", "description": "Daytime RGB imagery helps distinguish liquid-water clouds, ice clouds, and snow. Its colors are meaningful in daylight."},
    "ntmicro": {"label": "NT Microphysics", "description": "Nighttime RGB imagery helps distinguish low clouds and fog from higher clouds. Solar reflection affects its colors during daylight."},
}


def page_url(product):
    if product not in PRODUCTS:
        raise ValueError("Unknown satellite product")
    return (f"https://weather.cod.edu/satrad/?parms=local-{SECTOR}-{product}-48-0-100-1"
            "&checked=counties-map")


def latest_frames(frames, now, limit=FRAME_COUNT):
    """Return the latest unique source times, independent of a two-hour cutoff."""
    eligible={}
    for original in frames:
        try:
            moment=datetime.fromisoformat(original['time'].replace('Z','+00:00'))
            if moment.tzinfo is None or not now-timedelta(days=1)<=moment<=now:continue
            stamp=moment.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
            eligible[stamp]={**original,'time':stamp}
        except (KeyError,TypeError,ValueError):continue
    return [eligible[stamp] for stamp in sorted(eligible)[-limit:]]


def frame_window(frames, now):
    return dict(frameLimit=FRAME_COUNT,historyPolicy='latest-24-images',
                historyPending=max(0,FRAME_COUNT-len(frames)),
                windowStart=frames[0]['time'] if frames else now.isoformat().replace('+00:00','Z'),
                windowEnd=frames[-1]['time'] if frames else now.isoformat().replace('+00:00','Z'))


def parse_loop(html, product, now=None, frame_limit=FRAME_COUNT):
    if product not in PRODUCTS:
        raise ValueError("Unknown satellite product")
    now = now or datetime.now(timezone.utc)
    prefix = f"{BASE}/{product}/{SECTOR}.{product}."
    matches = set(re.findall(re.escape(prefix) + r"(\d{8}\.\d{6})\.jpg", html))
    frames = []
    for stamp in sorted(matches):
        try:
            moment = datetime.strptime(stamp, "%Y%m%d.%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        frames.append({"time": moment.isoformat().replace("+00:00", "Z"),
                       "url": prefix + stamp + ".jpg"})
    frames=latest_frames(frames,now,frame_limit)
    if not frames:
        raise ValueError("No satellite images are currently available")
    # All imagery and map overlays share the source's native 1600 x 900 grid.
    # It is an image viewer, not a geographic reprojection onto radar coordinates.
    boundaries = []
    for name in ("counties", "map"):
        prefix = f"{BASE}/maps/{SECTOR}_{name}.png"
        match = re.search(re.escape(prefix) + r"(?:\?v=\d+)?", html)
        if match:
            boundaries.append(match.group(0))
    return {"product": product, **PRODUCTS[product], "frames": frames,
            **frame_window(latest_frames(frames,now),now),
            "products": [{"id": key, "label": value["label"]} for key, value in PRODUCTS.items()],
            "boundaries": boundaries, "width": 1600, "height": 900,
            "source": "NOAA GOES-East imagery via College of DuPage NEXLAB",
            "sourceUrl": page_url(product), "fetchedAt": now.isoformat().replace("+00:00", "Z")}

