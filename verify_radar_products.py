"""Verify the selected prepared radar loops with retries for transient serving errors."""
import gzip
import json
import struct
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def verify(base):
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Expected an HTTPS site origin")

    def fetch(path):
        for attempt in range(8):
            try:
                with urlopen(Request(base+path, headers={"User-Agent": "Weather Lab radar verification"}), timeout=90) as response:
                    return response.read()
            except HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 7:
                    raise
            except (URLError, TimeoutError):
                if attempt == 7:
                    raise
            time.sleep(min(5*(attempt+1), 30))

    html = fetch("/").decode()
    if 'id="radar-product"' not in html or "radar-products-v1" not in html:
        raise ValueError("Updated radar selector was not served")
    for name in ("metar", "radar", "satellite", "forecast", "air-quality"):
        if f'id="tab-{name}"' not in html:
            raise ValueError("An existing weather tab is missing")
    default = json.loads(fetch("/api/radar?site=KMPX"))
    products = default.get("products", [])
    if len(products) < 3 or products[-1]["id"] != "storm-total":
        raise ValueError("Higher elevations and storm totals were not prepared")
    for product in products:
        endpoint = "/api/radar?site=KMPX" + ("&product="+product["id"] if product != products[0] else "")
        data = json.loads(fetch(endpoint))
        if not data.get("frames"):
            raise ValueError("Missing loop for "+product["label"])
        frame = data["frames"][-1]
        if not frame["url"].startswith("/api/prepared/radar/"):
            raise ValueError("Invalid prepared radar asset")
        raw = gzip.decompress(fetch(frame["url"]))
        length = struct.unpack(">I", raw[:4])[0]
        meta = json.loads(raw[4:4+length])
        if meta["id"] != frame["id"] or len(raw)-4-length != meta["gates"]*len(meta["azimuths"]):
            raise ValueError("Radar packet does not match its manifest")
        if product["id"] == "storm-total" and (meta.get("units") != "inches" or not meta.get("accumulationStart")):
            raise ValueError("Storm-total units or start time missing")
        print(f"{product['label']}: {len(data['frames'])} prepared frames", flush=True)


if __name__ == "__main__":
    verify(sys.argv[1].rstrip("/"))
