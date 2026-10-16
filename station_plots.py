"""Time and history helpers for official airport METAR plots."""
from datetime import datetime, timedelta, timezone
import math

WINDOW = timedelta(minutes=10)


def iso(moment):
    return moment.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def timestamp(text):
    try:
        stamp = datetime.fromisoformat(text.replace('Z', '+00:00'))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and low <= value <= high else None


def valid_saved(row, hour, age=WINDOW):
    stamp = timestamp(row.get('time'))
    return stamp is not None and hour-age <= stamp < hour


def history(frames, hour):
    selected, checks = {}, {}
    for frame in frames:
        target = timestamp(frame.get('hour'))
        if target is None or not hour-timedelta(hours=11) <= target <= hour:
            continue
        label = iso(target)
        if 'sourceHealth' in frame:
            checks[label] = frame['sourceHealth']
        for row in frame.get('stations', []):
            if not valid_saved(row, target):
                continue
            observed = timestamp(row['time'])
            rank = (abs((observed-(target-timedelta(minutes=7))).total_seconds()),
                    -observed.timestamp(), row.get('receiptTime', ''))
            key = (label, row['stationKey'])
            if key not in selected or rank[:2] < selected[key][0][:2] or (
                    rank[:2] == selected[key][0][:2] and rank[2] >= selected[key][0][2]):
                selected[key] = (rank, row)
    result = []
    for offset in reversed(range(12)):
        label = iso(hour-timedelta(hours=offset))
        result.append({'hour': label,
                       'stations': sorted((item[1] for (h, _), item in selected.items() if h == label),
                                          key=lambda r: r['stationKey']),
                       **({'sourceHealth': checks[label]} if label in checks else {})})
    return result
