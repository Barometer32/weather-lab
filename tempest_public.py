"""Experimental averages from the rendered public Tempest map detail panels.

This collector reads the same visible fields as a visitor. It does not call
private APIs, extract website keys, sign in, or bypass access challenges.
"""
from datetime import datetime, timedelta, timezone
import math
import re
from statistics import mean
import time
from zoneinfo import ZoneInfo

KEY = 'live/tempest-experiment-v1.json'
VERSION = 'tempest-public-panels-v1'
MAX_AGE_SECONDS = 600
POLL_SECONDS = 300
MAP_URL = 'https://tempestwx.com/map/139723/44.8053/-93.4113/12'
STATIONS = (
    ('211793','Clay St'),('238063','Minnesota St S'),('180161','Monroe St S'),
    ('135859','Granite Dr'),('139463','WeatherFlo Riley'),('236779','Cole Ct'),
    ('143206','Ridge Bluff Dr'),('138562','SW Eden Prairie'),('177349','Eagle Ridge Rd'),
    ('21964','Chaska'),('178958','Pampas Ct'),('81475','E 7th St'),
    ('216957','Parkview Dr'),('216676','Douglas Dr'),('109584','Stonebrooke Dr'),
)
CARDINALS = ('N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW')
UTC = timezone.utc


def iso(t):
    return t.astimezone(UTC).isoformat().replace('+00:00','Z')


def nearest(value):
    return math.floor(value+.5)


def station_url(identifier):
    return ('https://tempestwx.com/map/21964/44.8053/-93.4113/12' if identifier=='21964'
            else f'https://tempestwx.com/station/{identifier}/grid')


def temperature(text):
    m=re.fullmatch(r'\s*([+-]?\d+(?:\.\d+)?)\s*°\s*([FC])\s*',str(text))
    if not m:return None
    value=float(m[1]);value=value if m[2]=='F' else value*1.8+32
    return value if math.isfinite(value) and -150<=value<=160 else None


def wind_speed(text):
    m=re.fullmatch(r'\s*([+]?\d+(?:\.\d+)?)\s*(mph|km/h|kph|m/s|kt|kts|knots)\s*',str(text))
    if not m:return 0.0 if str(text).strip().lower()=='calm' else None
    factors={'mph':1,'km/h':1/1.609344,'kph':1/1.609344,'m/s':2.2369362921,'kt':1.150779448,'kts':1.150779448,'knots':1.150779448}
    value=float(m[1])*factors[m[2]]
    return value if 0<=value<=290 else None


def direction(text):
    text=str(text).strip().upper()
    if text in CARDINALS:return CARDINALS.index(text)*22.5
    m=re.fullmatch(r'(\d+(?:\.\d+)?)\s*°?',text)
    return float(m[1])%360 if m and 0<=float(m[1])<=360 else None


def report_time(text,zone,now):
    if zone!='America/Chicago':raise ValueError('Unexpected station timezone')
    wall=datetime.strptime(str(text).strip().upper(),'%m/%d/%Y %I:%M:%S %p')
    candidates=[wall.replace(tzinfo=ZoneInfo(zone),fold=fold).astimezone(UTC) for fold in (0,1)]
    allowed=[t for t in candidates if t<=now+timedelta(seconds=90)]
    if not allowed:raise ValueError('Station report is in the future')
    return max(allowed)


def parse_panel(panel,now):
    identifier=str(panel.get('stationId',''))
    if identifier not in dict(STATIONS):raise ValueError('Unexpected station ID')
    fields=panel.get('fields') or {}
    stamp=report_time(fields.get('Timestamp'),fields.get('Timezone'),now)
    temp=temperature(fields.get('Air Temperature'));dew=temperature(fields.get('Dew Point'))
    if temp is not None and not -130<=temp<=150:temp=None
    if dew is not None and temp is not None and dew>temp+1:dew=None
    bearing_text=fields.get('Wind Direction','')
    return {'stationId':identifier,'observedAt':iso(stamp),'tempF':temp,'dewpointF':dew,
            'wind':{'speedMph':wind_speed(fields.get('Wind Speed')),'direction':direction(bearing_text),
                    'variable':str(bearing_text).strip().upper() in ('VARIABLE','VRB')},
            'capturedAt':iso(now)}


PANEL_SCRIPT = """node => ({
 stationId:(node.querySelector('#station-name a')?.getAttribute('href')||'').split('/').pop(),
 fields:Object.fromEntries(Array.from(node.querySelectorAll('li'))
  .filter(row=>row.querySelector('.lv-param-label')&&row.querySelector('.lv-value-display'))
  .map(row=>[row.querySelector('.lv-param-label').textContent.trim(),row.querySelector('.lv-value-display').textContent.trim()]))
})"""


def browser_capture():
    """Bounded, single-browser UI collection; one map load for all 15 stations."""
    from playwright.sync_api import sync_playwright
    panels,errors=[],[]
    started=time.monotonic()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
        try:
            context=browser.new_context(locale='en-US',timezone_id='America/Chicago',viewport={'width':1363,'height':936})
            page=context.new_page()
            page.route('**/*',lambda route:route.abort() if route.request.resource_type in ('image','media','font') else route.continue_())
            page.goto(MAP_URL,wait_until='domcontentloaded',timeout=20000)
            try:
                page.get_by_role('button',name=STATIONS[0][1],exact=True).wait_for(state='attached',timeout=15000)
            except Exception:
                body=page.locator('body').inner_text(timeout=2000).lower()
                if any(s in body for s in ('verify you are human','checking your browser','access denied','sign in to continue')):
                    raise ValueError('Public station page requires access verification')
                raise ValueError('Public station map did not load')
            for identifier,name in STATIONS:
                if time.monotonic()-started>60:
                    errors.append({'stationId':identifier,'error':'Collection time limit reached'})
                    continue
                try:
                    buttons=page.get_by_role('button',name=name,exact=True)
                    selected=False
                    for i in range(min(buttons.count(),4)):
                        previous_text=page.locator('#list-view').text_content(timeout=2000) or ''
                        buttons.nth(i).press('Enter',timeout=2000)
                        # Header selection can precede the data response. Wait for
                        # the visible readings, not merely the new station name.
                        page.locator('#list-view').filter(has_not_text=previous_text).wait_for(state='visible',timeout=4000)
                        href=page.locator('#station-name a').get_attribute('href',timeout=2000)
                        if href!='/station/'+identifier:continue
                        page.locator('#station-detail .lv-value-display[data-param="timestamp"]').wait_for(state='attached',timeout=3000)
                        panel=page.locator('#station-detail').evaluate(PANEL_SCRIPT,timeout=2000)
                        if panel['stationId']!=identifier:raise ValueError('Station selection changed')
                        panels.append(panel);selected=True;break
                    if not selected:raise ValueError('Station marker unavailable')
                except Exception:
                    errors.append({'stationId':identifier,'error':'Public station panel unavailable'})
            context.close()
        finally:
            browser.close()
    return panels,errors


def collect(store,now,capture=None):
    previous=store.read_json(KEY) or {}
    old=previous.get('stations',[]) if previous.get('version')==VERSION else []
    pool={r['stationId']:r for r in old if r.get('stationId') in dict(STATIONS)}
    errors=[]
    try:panels,errors=(capture or browser_capture)()
    except Exception:panels=[];errors=[{'error':'Public Tempest map collection unavailable'}]
    parsed=0
    for panel in panels:
        try:
            row=parse_panel(panel,now)
            if row['observedAt']>=pool.get(row['stationId'],{}).get('observedAt',''):pool[row['stationId']]=row
            parsed+=1
        except (ValueError,TypeError,KeyError):errors.append({'stationId':panel.get('stationId'),'error':'Invalid station fields or timestamp'})
    snapshot={'version':VERSION,'checkedAt':iso(now),'lastSuccessAt':iso(now) if parsed else previous.get('lastSuccessAt'),
              'stations':list(pool.values()),'failures':errors,'source':'Tempest public station pages'}
    store.write_json(KEY,snapshot)
    if not parsed:raise ValueError('No Tempest panels could be read; prior report times retained')
    return {'stationsRead':parsed,'stationsIncluded':present(snapshot,now)['summary']['stationCount'],'failures':len(errors)}


def average_wind(rows):
    winds=[r['wind'] for r in rows if type((r.get('wind') or {}).get('speedMph')) in (int,float) and math.isfinite(r['wind']['speedMph']) and 0<=r['wind']['speedMph']<=290]
    if not winds:return {'speedMph':None,'cardinal':'Unavailable','stationCount':0}
    speed=mean(w['speedMph'] for w in winds)
    if nearest(speed)<=3:return {'speedMph':nearest(speed),'cardinal':'CALM','stationCount':len(winds)}
    east=north=0.0;bearings=0
    for w in winds:
        d=w.get('direction')
        if w['speedMph']<.5 or w.get('variable') or type(d) not in (int,float) or not math.isfinite(d):continue
        east+=w['speedMph']*math.sin(math.radians(d));north+=w['speedMph']*math.cos(math.radians(d));bearings+=1
    cardinal='Variable' if bearings or any(w.get('variable') for w in winds) else 'Unknown'
    bearing=None
    if math.hypot(east,north)>1e-6:
        bearing=math.degrees(math.atan2(east,north))%360
        cardinal=('N','NE','E','SE','S','SW','W','NW')[nearest(bearing/45)%8]
    return {'speedMph':nearest(speed),'direction':bearing,'cardinal':cardinal,'stationCount':len(winds)}


def present(saved,now):
    if not saved or saved.get('version')!=VERSION:raise ValueError('Tempest experiment is being prepared')
    pool={r['stationId']:r for r in saved.get('stations',[]) if r.get('stationId') in dict(STATIONS)}
    rows=[];included=[]
    for identifier,name in STATIONS:
        raw=pool.get(identifier);row={'stationId':identifier,'name':name,'url':station_url(identifier),'status':'Unavailable','included':False}
        if raw:
            row.update(raw)
            try:
                age=(now-datetime.fromisoformat(raw['observedAt'].replace('Z','+00:00'))).total_seconds()
                row['ageMinutes']=max(0,age/60)
                complete=all(type(raw.get(k)) in (int,float) and math.isfinite(raw[k]) for k in ('tempF','dewpointF'))
                complete=complete and -130<=raw['tempF']<=150 and -150<=raw['dewpointF']<=raw['tempF']+1
                row['included']=complete and -90<=age<=MAX_AGE_SECONDS
                row['status']='Included' if row['included'] else 'Stale' if age>MAX_AGE_SECONDS else 'Incomplete'
            except (ValueError,TypeError,KeyError):row['status']='Unavailable'
            if row['included']:included.append(row)
        rows.append(row)
    summary={'stationCount':len(included),'totalStations':len(STATIONS),'tempF':None,'dewpointF':None,'wind':average_wind(included),
             'oldestReportAt':min((r['observedAt'] for r in included),default=None),'newestReportAt':max((r['observedAt'] for r in included),default=None)}
    if included:
        summary.update(tempF=nearest(mean(r['tempF'] for r in included)),dewpointF=nearest(mean(r['dewpointF'] for r in included)))
    last=saved.get('lastSuccessAt');stale=not last or (now-datetime.fromisoformat(last.replace('Z','+00:00'))).total_seconds()>600
    return {'version':VERSION,'experimental':True,'stations':rows,'summary':summary,'checkedAt':saved.get('checkedAt'),'serverTime':iso(now),
            'stale':stale,'collectionFailures':len(saved.get('failures',[])),'updateIntervalSeconds':POLL_SECONDS,
            'maxReportAgeSeconds':MAX_AGE_SECONDS,'source':'WeatherFlow Tempest public station pages'}
