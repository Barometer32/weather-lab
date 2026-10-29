"""Hourly, fixed-region snapshots of the same public AirNow layers MPCA uses."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from hashlib import sha256
import json
import math
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageChops, ImageDraw

UTC = timezone.utc
VERSION = 'mn-region-v2'
LEGACY_VERSION = 'mn-region-v1'
MAP_STYLE = 'contours-only-no-labels'
CHECK_MINUTES = list(range(3, 60, 5))
HISTORY = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/AirNow24HrCombined/FeatureServer/0'
# Entire Minnesota, including the Northwest Angle and the Arrowhead.
BOUNDS = [-97.65, 43.2, -89.1, 49.65]
CONTOURS = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/AirNowLatestContoursCombined/FeatureServer/0'
BASE = 'https://utility.arcgis.com/usrsvcs/servers/6907e02ec8474c6580e269c2b3f68d81/rest/services/base/aqi_base_bg_light/MapServer'
OVERLAY = 'https://utility.arcgis.com/usrsvcs/servers/b4b392805417402d8d0510c586b89d87/rest/services/base/aqi_basemap/MapServer'
COLORS = {1:'#00e400', 2:'#ffff00', 3:'#ff7e00', 4:'#ff0000', 5:'#8f3f97', 6:'#7e0023'}


def iso(value):
    return value.astimezone(UTC).isoformat().replace('+00:00', 'Z')


def moment(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(UTC)


def mercator(lon, lat):
    return lon * math.pi * 6378137 / 180, 6378137 * math.log(math.tan(math.pi/4 + math.radians(lat)/2))


XMIN, YMIN = mercator(*BOUNDS[:2])
XMAX, YMAX = mercator(*BOUNDS[2:])
WIDTH = 1100
HEIGHT = round(WIDTH * (YMAX-YMIN)/(XMAX-XMIN))


def download(url):
    request = Request(url, headers={'User-Agent':'J-Weather (https://github.com/Barometer32/weather-lab)'})
    with urlopen(request, timeout=30) as response:
        result = response.read(8_000_001)
    if len(result)>8_000_000:
        raise ValueError('Air quality response exceeded its size limit')
    return result


def query(service, fields, fetch, where='1=1'):
    rows = []
    for offset in range(0, 10000, 2000):
        params = dict(f='json',where=where,geometry=','.join(map(str,BOUNDS)),
                      geometryType='esriGeometryEnvelope',inSR=4326,outSR=3857,
                      spatialRel='esriSpatialRelIntersects',outFields=fields,returnGeometry='true',
                      maxAllowableOffset=100,geometryPrecision=1,resultRecordCount=2000,resultOffset=offset)
        data = json.loads(fetch(service+'/query?'+urlencode(params)))
        if data.get('error') or not isinstance(data.get('features'),list):
            raise ValueError('AirNow query failed')
        rows.extend(data['features'])
        if not data.get('exceededTransferLimit'):
            return rows
        if not data['features']:
            break
    raise ValueError('AirNow response is incomplete')


def overlay_styles():
    def polygon(identifier,source,color,width):
        return dict(id=identifier,source=dict(type='mapLayer',mapLayerId=source),
                    drawingInfo=dict(showLabels=False,renderer=dict(type='simple',symbol=dict(
                        type='esriSFS',style='esriSFSNull',outline=dict(type='esriSLS',style='esriSLSSolid',color=color,width=width)))))
    # Only boundary and lake layers: explicitly omit both city label layers.
    # First dynamic layer is drawn on top. Keep county/state outlines visible.
    return [polygon(101,1,[180,180,180,255],1.5),polygon(1,1,[255,255,255,240],7),
            polygon(4,4,[214,214,214,255],.8),dict(id=18,source=dict(type='mapLayer',mapLayerId=18),drawingInfo=dict(transparency=0,showLabels=False,renderer=dict(type='simple',symbol=dict(type='esriSFS',style='esriSFSSolid',color=[166,187,194,255],outline=dict(type='esriSLS',style='esriSLSNull'))))),
            polygon(20,20,[160,160,160,255],1)]


def basemap(store,kind,fetch):
    key=f'air-quality/maps/{VERSION}-{MAP_STYLE}-{kind}.png'
    raw=store.read(key)
    if raw is None:
        params=dict(f='image',bbox=','.join(map(str,[XMIN,YMIN,XMAX,YMAX])),bboxSR=3857,imageSR=3857,
                    size=f'{WIDTH},{HEIGHT}',dpi=96,format='png32',transparent='true')
        if kind=='overlay':params['dynamicLayers']=json.dumps(overlay_styles(),separators=(',',':'))
        raw=fetch((BASE if kind=='base' else OVERLAY)+'/export?'+urlencode(params))
        decode_image(raw)
        store.write(key,raw,'image/png')
    return decode_image(raw)


def decode_image(raw):
    with Image.open(BytesIO(raw)) as opened:
        if opened.size != (WIDTH,HEIGHT):
            raise ValueError('Air quality basemap dimensions changed')
        return opened.convert('RGBA')


def xy(point):
    return ((point[0]-XMIN)/(XMAX-XMIN)*WIDTH,(YMAX-point[1])/(YMAX-YMIN)*HEIGHT)


def render(contours,base,overlay):
    image=base.copy()
    for feature in contours:
        color=COLORS.get(feature.get('attributes',{}).get('gridcode'))
        rings=feature.get('geometry',{}).get('rings',[])
        if not color or not rings:continue
        mask=Image.new('1',(WIDTH,HEIGHT))
        # Even/odd ring filling preserves holes and disjoint polygons.
        for ring in rings:
            if len(ring)<3:continue
            part=Image.new('1',(WIDTH,HEIGHT));ImageDraw.Draw(part).polygon([xy(p) for p in ring],fill=1)
            mask=ImageChops.logical_xor(mask,part)
        image.paste(color,(0,0,WIDTH,HEIGHT),mask.convert('L'))
    image=Image.alpha_composite(image,overlay)
    output=BytesIO();image.convert('RGB').save(output,format='PNG',optimize=True)
    return output.getvalue()


def recent_frames(data,now):
    # Normalize the first archive's capture-time labels without losing its maps.
    # The twelve-hour window is anchored to the latest *source* hour, so normal
    # upstream latency does not shorten an otherwise complete twelve-hour loop.
    result={}
    for original in (data or {}).get('frames',[]):
        try:
            frame=dict(original)
            if frame.get('version') not in (LEGACY_VERSION,VERSION):continue
            source=moment(frame['sourceTime'])
            captured=moment(frame.get('capturedAt') or frame['time'])
            if source>now or captured>now or captured<now-timedelta(days=1):continue
            frame.update(time=iso(source),sourceTime=iso(source),capturedAt=iso(captured))
            slot=iso(source.replace(minute=0,second=0,microsecond=0))
            previous=result.get(slot)
            if previous is None or moment(previous['capturedAt'])<=captured:result[slot]=frame
        except (KeyError,TypeError,ValueError):continue
    if not result:return []
    latest=max(moment(f['time']) for f in result.values()).replace(minute=0,second=0,microsecond=0)
    cutoff=latest-timedelta(hours=11)
    return sorted((f for f in result.values() if moment(f['time'])>=cutoff),key=lambda f:f['time'])


def source_groups(rows,now):
    groups={}
    for feature in rows:
        attrs=feature.get('attributes',{});stamp=attrs.get('Timestamp')
        if attrs.get('gridcode') not in COLORS or not feature.get('geometry',{}).get('rings'):continue
        if not isinstance(stamp,(int,float)) or not math.isfinite(stamp):continue
        try:source=datetime.fromtimestamp(stamp/1000,UTC)
        except (OverflowError,OSError,ValueError):continue
        if source>now or source<now-timedelta(days=1):continue
        slot=source.replace(minute=0,second=0,microsecond=0)
        groups.setdefault(slot,[]).append(feature)
    return groups


def collect(store,now,fetch=None):
    now=now.astimezone(UTC);fetch=fetch or download
    previous=store.read_json('live/air-quality.json') or {}
    frames=recent_frames(previous,now)
    groups=source_groups(query(CONTOURS,'gridcode,Unixtime,Timestamp',fetch),now)
    if not groups:raise ValueError('AirNow contours are unavailable; previous snapshot retained')
    newest=max(groups)
    # Archive real source hours missed between collections. The public 24-hour
    # combined-contour service uses the same gridcode and Timestamp fields.
    latest=max([newest]+[moment(frame['sourceTime']).replace(minute=0,second=0,microsecond=0) for frame in frames])
    wanted=[latest-timedelta(hours=n) for n in range(12)]
    present={moment(frame['sourceTime']).replace(minute=0,second=0,microsecond=0) for frame in frames}|set(groups)
    missing=[hour for hour in wanted if hour not in present]
    last_backfill=previous.get('backfillCheckedAt');backfill_errors=0
    try:can_backfill=not last_backfill or now-moment(last_backfill)>=timedelta(minutes=15)
    except (TypeError,ValueError):can_backfill=True
    if missing and can_backfill:
        def recover_hour(hour):
            end=hour+timedelta(hours=1)
            where=f"Timestamp >= timestamp '{hour.strftime('%Y-%m-%d %H:%M:%S')}' AND Timestamp < timestamp '{end.strftime('%Y-%m-%d %H:%M:%S')}'"
            try:
                rows=source_groups(query(HISTORY,'gridcode,Unixtime,Timestamp',fetch,where),now)
                return hour,rows.get(hour),False
            except Exception:
                return hour,None,True
        with ThreadPoolExecutor(max_workers=3) as pool:
            for hour,rows,failed in pool.map(recover_hour,missing):
                if rows:groups[hour]=rows
                backfill_errors+=int(failed)
        last_backfill=iso(now)
    geography=None
    for slot,contours in sorted(groups.items()):
        if slot not in wanted:continue
        source=datetime.fromtimestamp(max(f['attributes']['Timestamp'] for f in contours)/1000,UTC)
        canonical=sorted(json.dumps(f,sort_keys=True,separators=(',',':')) for f in contours)
        digest=sha256(json.dumps([MAP_STYLE,canonical],separators=(',',':')).encode()).hexdigest()
        existing=next((f for f in frames if moment(f['sourceTime']).replace(minute=0,second=0,microsecond=0)==slot),None)
        if existing and existing.get('version')==VERSION and existing.get('dataHash')==digest:continue
        if geography is None:
            with ThreadPoolExecutor(max_workers=2) as pool:
                b=pool.submit(basemap,store,'base',fetch);o=pool.submit(basemap,store,'overlay',fetch)
                geography=(b.result(),o.result())
        png=render(contours,*geography)
        key=f'air-quality/{VERSION}/{source.strftime("%Y%m%d%H%M%S")}-{digest[:16]}.png'
        frame=dict(version=VERSION,time=iso(source),sourceTime=iso(source),capturedAt=iso(now),
                   url='/api/prepared/'+key,dataHash=digest,style=MAP_STYLE)
        store.write(key,png,'image/png')
        frames=[f for f in frames if moment(f['sourceTime']).replace(minute=0,second=0,microsecond=0)!=slot]+[frame]
    frames=recent_frames({'frames':frames},now)
    present={moment(frame['sourceTime']).replace(minute=0,second=0,microsecond=0) for frame in frames}
    missing=[iso(hour) for hour in reversed(wanted) if hour not in present]
    store.write_json('live/air-quality.json',dict(version=VERSION,timeBasis='source',checkedAt=iso(now),bounds=BOUNDS,
        width=WIDTH,height=HEIGHT,frames=frames,source='EPA AirNow combined AQI contours used by MPCA',
        checkMinutes=CHECK_MINUTES,backfillCheckedAt=last_backfill,missingHours=missing,backfillErrors=backfill_errors))
    return {'frames':len(frames),'sourceTime':iso(newest),'missingHours':missing,'backfillErrors':backfill_errors}


def public_manifest(data,now):
    frames=recent_frames(data,now)
    if not frames:raise ValueError('No recent Air Q snapshots have been captured yet')
    return {**data,'frames':frames,'historyPending':len(frames)<12,'timeBasis':'source','checkMinutes':CHECK_MINUTES}


def main():
    from realtime import get_store
    store=get_store()
    if store is None:raise ValueError('WEATHER_DATA_BUCKET is required')
    print(json.dumps(collect(store,datetime.now(UTC))))


if __name__=='__main__':main()
