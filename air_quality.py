"""Hourly, fixed-region snapshots of the same public AirNow layers MPCA uses."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import math
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageChops, ImageDraw, ImageFont

UTC = timezone.utc
VERSION = 'mn-region-v1'
# Moorhead/Bemidji/Hibbing south to the Iowa border, including western Wisconsin.
BOUNDS = [-97.35, 43.15, -91.0, 47.65]
CONTOURS = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/AirNowLatestContoursCombined/FeatureServer/0'
MONITORS = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Air%20Now%20Current%20Monitor%20Data%20Public/FeatureServer/0'
BASE = 'https://utility.arcgis.com/usrsvcs/servers/6907e02ec8474c6580e269c2b3f68d81/rest/services/base/aqi_base_bg_light/MapServer'
OVERLAY = 'https://utility.arcgis.com/usrsvcs/servers/b4b392805417402d8d0510c586b89d87/rest/services/base/aqi_basemap/MapServer'
COLORS = {1:'#00e400', 2:'#ffff00', 3:'#ff7e00', 4:'#ff0000', 5:'#8f3f97', 6:'#7e0023'}
CITIES = ['Albert Lea','Alexandria','Bemidji','Brainerd','Duluth','Hibbing','Mankato','Marshall','Worthington','Ortonville','Hinckley','Two Harbors','Moorhead','Minneapolis','Rochester']


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
    cities = dict(id=2,source=dict(type='mapLayer',mapLayerId=2),
        definitionExpression='Name IN ('+','.join("'"+name+"'" for name in CITIES)+')',
        drawingInfo=dict(renderer=dict(type='simple',symbol=dict(type='esriSMS',style='esriSMSCircle',size=1,color=[0,0,0,0])),
            showLabels=True,labelingInfo=[dict(labelPlacement='esriServerPointLabelPlacementAboveRight',
                labelExpression='[Name]',useCodedValues=False,symbol=dict(type='esriTS',color=[55,55,55,255],
                    haloColor=[255,255,255,255],haloSize=1.2,font=dict(family='Arial',size=10,weight='bold')))]))
    # First dynamic layer is drawn on top. Keep county/state outlines visible.
    return [cities,polygon(101,1,[180,180,180,255],1.5),polygon(1,1,[255,255,255,240],7),
            polygon(4,4,[214,214,214,255],.8),dict(id=18,source=dict(type='mapLayer',mapLayerId=18)),
            polygon(20,20,[160,160,160,255],1)]


def basemap(store,kind,fetch):
    key=f'air-quality/maps/{VERSION}-{kind}.png'
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


def category(value):
    for maximum,code in [(50,1),(100,2),(150,3),(200,4),(300,5),(5000,6)]:
        if value<=maximum:return code
    return 6


def render(contours,monitors,base,overlay):
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
    draw=ImageDraw.Draw(image);font=ImageFont.load_default(size=18)
    count=0;times=[]
    for feature in monitors:
        attrs=feature.get('attributes',{});value=attrs.get('OZONEPM_AQI_SORT');point=feature.get('geometry',{})
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or value>5000:continue
        if not all(isinstance(point.get(k),(int,float)) and math.isfinite(point[k]) for k in ['x','y']):continue
        x,y=xy([point['x'],point['y']])
        if not 0<=x<=WIDTH or not 0<=y<=HEIGHT:continue
        fill=COLORS[category(value)];draw.ellipse((x-14,y-14,x+14,y+14),fill=fill,outline='#111',width=1)
        draw.text((x,y),str(round(value)),font=font,fill='white' if value>200 else 'black',anchor='mm')
        count+=1
        if isinstance(attrs.get('ValidTime'),(int,float)):times.append(attrs['ValidTime']/1000)
    if not count:raise ValueError('No usable AirNow monitors in this region')
    output=BytesIO();image.convert('RGB').save(output,format='PNG',optimize=True)
    return output.getvalue(),count,times


def recent_frames(data,now):
    cutoff=now.replace(minute=0,second=0,microsecond=0)-timedelta(hours=11)
    result={}
    for frame in (data or {}).get('frames',[]):
        try:
            captured=moment(frame['time']);slot=captured.replace(minute=0,second=0,microsecond=0)
            if cutoff<=captured<=now and frame.get('version')==VERSION:result[iso(slot)]=frame
        except (KeyError,TypeError,ValueError):continue
    return sorted(result.values(),key=lambda f:f['time'])


def collect(store,now,fetch=None):
    now=now.astimezone(UTC);fetch=fetch or download
    previous=store.read_json('live/air-quality.json') or {}
    frames=recent_frames(previous,now)
    slot=now.replace(minute=0,second=0,microsecond=0)
    if any(moment(f['time']).replace(minute=0,second=0,microsecond=0)==slot for f in frames):
        return {'frames':len(frames),'status':'already captured this hour'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(query,CONTOURS,'gridcode,Unixtime,Timestamp',fetch),
              pool.submit(query,MONITORS,'AQSID,SiteName,OZONEPM_AQI_SORT,ValidTime',fetch,'OZONEPM_AQI_SORT >= 0'),
              pool.submit(basemap,store,'base',fetch),pool.submit(basemap,store,'overlay',fetch)]
        contours,monitors,base,overlay=[job.result() for job in jobs]
    stamps=[f.get('attributes',{}).get('Timestamp') for f in contours if f.get('attributes',{}).get('gridcode') in COLORS and f.get('geometry',{}).get('rings')]
    stamps=[v/1000 for v in stamps if isinstance(v,(int,float)) and math.isfinite(v)]
    if not stamps:raise ValueError('AirNow contours are unavailable; previous snapshot retained')
    png,count,monitor_times=render(contours,monitors,base,overlay)
    key=f'air-quality/{VERSION}/{now.strftime("%Y%m%d%H%M%S")}.png'
    frame=dict(version=VERSION,time=iso(now),url='/api/prepared/'+key,
               sourceTime=iso(datetime.fromtimestamp(max(stamps),UTC)),monitors=count,
               monitorOldest=iso(datetime.fromtimestamp(min(monitor_times),UTC)) if monitor_times else None,
               monitorNewest=iso(datetime.fromtimestamp(max(monitor_times),UTC)) if monitor_times else None)
    store.write(key,png,'image/png')
    frames.append(frame)
    store.write_json('live/air-quality.json',dict(version=VERSION,checkedAt=iso(now),bounds=BOUNDS,
        width=WIDTH,height=HEIGHT,frames=frames[-12:],source='EPA AirNow public feeds used by MPCA',captureMinute=5))
    return {'frames':len(frames[-12:]),'monitors':count,'sourceTime':frame['sourceTime']}


def public_manifest(data,now):
    frames=recent_frames(data,now)
    if not frames:raise ValueError('No recent Air Q snapshots have been captured yet')
    return {**data,'frames':frames,'historyPending':len(frames)<12}


def main():
    from realtime import get_store
    store=get_store()
    if store is None:raise ValueError('WEATHER_DATA_BUCKET is required')
    print(json.dumps(collect(store,datetime.now(UTC))))


if __name__=='__main__':main()
