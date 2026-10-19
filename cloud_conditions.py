"""Reported METAR sky cover and lowest ceiling, including saved raw reports."""
import math
import re

COVER = {
    'CLR': (0, 0, 0., 'Clear below the sensor limit'),
    'SKC': (0, 0, 0., 'Sky clear'),
    'FEW': (1, 2, .25, 'Few clouds'),
    'SCT': (3, 4, .5, 'Scattered clouds'),
    'BKN': (5, 7, .75, 'Broken clouds'),
    'OVC': (8, 8, 1., 'Overcast'),
}
SPECIAL = {'VV': 'Sky obscured', 'NSC': 'No significant cloud',
           'NCD': 'No cloud detected', 'CAVOK': 'CAVOK cloud criteria'}


def height(value):
    return (round(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 <= value <= 60000 else None)


def layers_from_report(row):
    layers = []
    supplied = row.get('cloudLayers') or row.get('layers') or []
    for layer in (supplied if isinstance(supplied, list) else [])[:20]:
        if not isinstance(layer, dict):
            continue
        cover = 'VV' if layer.get('cover') == 'OVX' else layer.get('cover')
        if cover not in COVER and cover not in SPECIAL:
            continue
        base = height(layer.get('baseFtAGL')) if cover in ('FEW', 'SCT', 'BKN', 'OVC', 'VV') else None
        layers.append({'cover': cover, 'baseFtAGL': base,
                       'heightType': 'verticalVisibility' if cover == 'VV' else 'cloudBase'})
    if not layers:
        # Existing twelve-hour snapshots already retain genuine raw METARs.
        # Decode their cloud groups without any new download or changed time.
        body = str(row.get('rawOb') or '').split(' RMK')[0]
        if re.search(r'\bNIL\b', body):
            return []
        for match in re.finditer(r'(?<!\S)(FEW|SCT|BKN|OVC|VV)(\d{3}|///)(?:CB|TCU)?(?=\s|=|$)', body):
            cover, code = match.groups()
            base = height(int(code)*100) if code.isdigit() else None
            layers.append({'cover': cover, 'baseFtAGL': base,
                           'heightType': 'verticalVisibility' if cover == 'VV' else 'cloudBase'})
        if not layers:
            clear = re.search(r'\b(CLR|SKC|NSC|NCD|CAVOK)\b', body)
            if clear:
                layers.append({'cover': clear[1], 'baseFtAGL': None, 'heightType': 'cloudBase'})
    return sorted(layers, key=lambda layer: (layer['baseFtAGL'] is None, layer['baseFtAGL'] or 0))


def summarize(row):
    layers = layers_from_report(row)
    codes = {layer['cover'] for layer in layers}
    code = ('VV' if 'VV' in codes else
            max((c for c in codes if c in COVER), key=lambda c: COVER[c][2], default=None))
    if code is None and codes:
        code = sorted(codes)[0]
    if code in COVER:
        low, high, fill, text = COVER[code]
        sky = {'code': code, 'oktaRange': [low, high], 'displayFraction': fill,
               'description': text, 'representativeFill': code in ('FEW', 'SCT', 'BKN')}
    else:
        sky = {'code': code, 'oktaRange': None, 'displayFraction': None,
               'description': SPECIAL.get(code, 'Cloud cover not reported'), 'representativeFill': False}
    candidates = [layer for layer in layers if layer['cover'] in ('BKN', 'OVC')]
    kind = 'ceiling'
    if not candidates and 'VV' in codes:
        candidates = [layer for layer in layers if layer['cover'] == 'VV']
        kind = 'verticalVisibility'
    ceiling = None
    if candidates:
        # An unknown-height ceiling layer prevents claiming a known lowest base.
        missing = next((layer for layer in candidates if layer['baseFtAGL'] is None), None)
        first = missing or min(candidates, key=lambda layer: layer['baseFtAGL'])
        ceiling = {'cover': first['cover'], 'baseFtAGL': first['baseFtAGL'], 'kind': kind}
    return {'cloudLayers': layers, 'skyCover': sky, 'ceiling': ceiling}

