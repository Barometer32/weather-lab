"""Independent NOAA STAR image-coordinate cloud viewer; no COD feed changes."""
from datetime import datetime, timedelta, timezone
import re

PRODUCTS = {
    "combo": {"band": "DayNightCloudMicroCombo", "label": "Day / night cloud RGB", "description": "NOAA combines Day Cloud Phase in daylight and Nighttime Microphysics after dark. RGB colors describe cloud properties; they do not measure cloud-base height."},
    "geocolor": {"band": "GEOCOLOR", "label": "GeoColor", "description": "Natural-looking color by day; an infrared cloud view at night. Credit: CIRA / NOAA. Nighttime city lights are a static reference layer."},
    "infrared": {"band": "13", "label": "Infrared cloud tops", "description": "Band 13 clean infrared works day and night and shows cloud-top brightness temperatures. Temperature is not a direct measurement of cloud height or cloud base."},
}


def page_url(product):
    if product not in PRODUCTS:
        raise ValueError("Unknown NOAA cloud product")
    return ("https://www.star.nesdis.noaa.gov/GOES/sector_band.php?sat=G19&sector=umv"
            f"&band={PRODUCTS[product]['band']}&length=36")


def parse_loop(html, product, now):
    page_url(product)
    band = PRODUCTS[product]["band"]
    prefix = f"https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/umv/{band}/"
    matches = set(re.findall(re.escape(prefix)+r"(\d{11})_GOES19-ABI-umv-"+re.escape(band)+r"-1200x1200\.jpg", html))
    frames = []
    for stamp in sorted(matches):
        try:
            moment = datetime.strptime(stamp, "%Y%j%H%M").replace(tzinfo=timezone.utc)
            if moment.strftime("%Y%j%H%M") != stamp or not now-timedelta(hours=2) <= moment <= now:
                continue
        except ValueError:
            continue
        frames.append({"time": moment.isoformat().replace("+00:00", "Z"),
                       "url": f"{prefix}{stamp}_GOES19-ABI-umv-{band}-1200x1200.jpg"})
    if not frames:
        raise ValueError("No recent NOAA cloud images are available")
    return {"product": product, "label": PRODUCTS[product]["label"], "description": PRODUCTS[product]["description"],
            "frames": frames, "width": 1200, "height": 1200, "sourceUrl": page_url(product),
            "source": "NOAA / NESDIS / STAR (GeoColor: CIRA / NOAA)",
            "windowStart": (now-timedelta(hours=2)).isoformat().replace("+00:00", "Z")}
