"""Three-airport average from the same prepared direct NOAA RAPMET feed."""
from datetime import datetime
import math
from statistics import mean

STATIONS=("KMSP","KFCM","KMIC")
CARDINALS=("N","NE","E","SE","S","SW","W","NW")


def nearest(value):
    # Match conventional display rounding, including .5 cases.
    return math.floor(value+.5)


def wind_average(rows):
    speeds=[(r.get("wind") or {}).get("speedMph") for r in rows]
    if not all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=290 for v in speeds):
        return {"speedMph":None,"direction":None,"cardinal":"Unknown"}
    speed=mean(speeds)
    if speed<.5:return {"speedMph":nearest(speed),"direction":None,"cardinal":"Calm"}
    east=north=0.0
    for r,s in zip(rows,speeds):
        if s<.5:continue
        w=r.get("wind") or {};d=w.get("direction")
        if type(d) not in (int,float) or not math.isfinite(d) or not 0<=d<=360:
            return {"speedMph":nearest(speed),"direction":None,"cardinal":"Variable" if w.get("variable") else "Unknown"}
        east+=s*math.sin(math.radians(d));north+=s*math.cos(math.radians(d))
    if math.hypot(east,north)<1e-6:return {"speedMph":nearest(speed),"direction":None,"cardinal":"Variable"}
    direction=math.degrees(math.atan2(east,north))%360
    return {"speedMph":nearest(speed),"direction":direction,"cardinal":CARDINALS[nearest(direction/45)%8]}


def present(saved,now):
    import rapmet
    if not saved or saved.get("version")!=rapmet.VERSION:raise ValueError("Airport observations are not prepared")
    pool={}
    for r in saved.get("metroReports",saved.get("stations",[])):
        if r.get("station") in STATIONS and rapmet.eligible(r,now):pool[r["station"],r["time"]]=r
    times=[{t for s,t in pool if s==station and rapmet.complete(pool[s,t])} for station in STATIONS]
    common=set.intersection(*times)
    observed=max(common,default=None)
    current=None
    if observed:
        rows=[pool[s,observed] for s in STATIONS]
        temp=mean(r["tempC"] for r in rows);dew=mean(r["dewpointC"] for r in rows)
        current={"observedAt":observed,"tempC":temp,"dewpointC":dew,
                 "tempF":nearest(temp*1.8+32),"dewpointF":nearest(dew*1.8+32),"wind":wind_average(rows)}
    else:
        rows=[max((r for (s,_),r in pool.items() if s==station),key=lambda r:r["time"],default=None) for station in STATIONS]
        rows=[r for r in rows if r]
    checked=saved.get("checkedAt")
    stale=not checked or (now-datetime.fromisoformat(checked.replace("Z","+00:00"))).total_seconds()>600
    age=(now-datetime.fromisoformat(observed.replace("Z","+00:00"))).total_seconds()/60 if observed else None
    return {"current":current,"stations":rows,"stationIds":list(STATIONS),"checkedAt":checked,
            "serverTime":rapmet.iso(now),"ageMinutes":age,"sourceDelayed":age is None or age>15,"stale":stale,
            "updateIntervalSeconds":300,"source":saved.get("feed"),"waiting":current is None,
            "calculation":"equal Celsius average of all three airports at the same five-minute report time; convert to Fahrenheit and round once"}
