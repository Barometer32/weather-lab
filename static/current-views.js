"use strict";
window.WeatherCurrent = (()=>{
  const el=id=>document.getElementById(id),fields={temperatureF:"current-temperature",dewpointF:"current-dewpoint",windMph:"current-wind"};
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const dateClock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  const finite=Number.isFinite;
  const degree=n=>finite(n)?`${Math.round(n)}°F`:"—";
  const wind=(speed,direction)=>!finite(speed)?"—":Math.round(speed)===0?"0":`${finite(direction)?directions[Math.round(direction/45)%8]:"Variable"} ${Math.round(speed)}`;
  let data=null,busy=false,serial=0,queued=false,readError="",saved=false;
  function sun(){
    const p=window.WeatherLocation.get(),now=window.WeatherSun.now?.()||new Date();
    el("current-sun").textContent=`${window.WeatherSun.elevation(now,p.latitude,p.longitude).toFixed(1)}°`;
  }
  function add(tag,text,parent){const n=document.createElement(tag);n.textContent=text;parent.append(n);return n;}
  const recent=field=>field?.observationStart&&Date.now()-Date.parse(field.observationStart)<=1800000;
  function render(){
    sun();if(!data)return;
    const f=data.fields||{};
    el(fields.temperatureF).textContent=degree(recent(f.temperatureF)?f.temperatureF.value:null);
    el(fields.dewpointF).textContent=degree(recent(f.dewpointF)?f.dewpointF.value:null);
    el(fields.windMph).textContent=wind(recent(f.windMph)?f.windMph.value:null,data.windDirection);
    const range=data.observationStart&&data.observationEnd?`${dateClock.format(new Date(data.observationStart))}–${clock.format(new Date(data.observationEnd))}`:"No recent observations";
    // Each field's time uses the same unrounded station weights as its estimate.
    // Equal weight across the displayed measurements gives one representative time.
    const times=Object.values(f).filter(field=>recent(field)&&finite(field.value)).map(field=>Date.parse(field.representativeTime)).filter(finite);
    const time=times.length?new Date(Math.round(times.reduce((sum,t)=>sum+t,0)/times.length/60000)*60000):null;
    el("current-time").textContent=time?`${saved?"Saved estimate · ":"Local estimate · "}${dateClock.format(time)}`:"No recent observations";
    el("current-time").title="Weighted observation time, rounded to the nearest minute; sun height uses the current time.";
    el("current-observation-range").textContent=`Observation range · ${range}`;
    const status=readError||data.message||(data.stale?"Observation collection is delayed. Only reports still within 30 minutes are used.":data.sourceErrors?.length?"Some observation feeds are delayed; available recent stations are used.":"");
    el("current-status").textContent=status;el("current-status").hidden=!status;
    const list=el("current-station-list");list.replaceChildren();
    for(const row of data.stations||[]){
      const card=document.createElement("article");card.className="contributor";
      add("strong",`${row.name||row.station} (${row.station})`,card);
      add("p",`${row.network||row.provider||row.source} · ${(row.distanceKm*.621371).toFixed(1)} mi · ${clock.format(new Date(row.time))}`,card);
      add("p",`${degree(row.tempF)} · Dew ${degree(row.dewpointF)} · Wind ${wind(row.wind?.speedMph,row.wind?.direction)}`,card);
      add("p",Object.entries(row.weightsPct||{}).map(([name,value])=>`${name} ${Math.round(value)}%`).join(" · "),card);
      list.append(card);
    }
  }
  function savedKey(){const p=window.WeatherLocation.get();return `weather-current-${p.latitude.toFixed(4)},${p.longitude.toFixed(4)}`;}
  async function load(){
    if(busy){queued=true;return;}busy=true;
    const request=serial,p=window.WeatherLocation.get();if(data)render();
    try{
      const response=await fetch("/api/current",{method:"POST",headers:{"Content-Type":"application/json"},cache:"no-store",body:JSON.stringify({latitude:p.latitude,longitude:p.longitude}),signal:AbortSignal.timeout(20000)});
      const next=await response.json();if(!response.ok)throw Error(next.error||"Current observations unavailable.");
      if(request!==serial)return;
      data=next;readError="";saved=false;
      if(data.serverTime)window.WeatherSun.sync(data.serverTime);
      // Keep just one selected-location snapshot, never a travel history.
      try{localStorage.setItem("weather-current-last",JSON.stringify({key:savedKey(),storedAt:Date.now(),data}));}catch(_){}
      render();
    }catch(error){
      if(request!==serial)return;
      readError="Could not refresh observations. Check the displayed observation times.";saved=!!data;
      if(data)render();else{el("current-time").textContent="Recent observations unavailable";el("current-status").hidden=false;el("current-status").textContent=readError;}
    }finally{busy=false;if(queued){queued=false;load();}}
  }
  function restore(){
    try{
      const old=JSON.parse(localStorage.getItem("weather-current-last"));
      if(old?.key===savedKey()&&Date.now()-old.storedAt<300000&&old.data?.observationStart&&Date.now()-Date.parse(old.data.observationStart)<=1800000){data=old.data;saved=true;render();}
    }catch(_){}
  }
  window.WeatherLocation.subscribe(()=>{
    serial++;data=null;readError="";saved=false;
    for(const id of Object.values(fields))el(id).textContent="—";
    el("current-time").textContent="Loading recent observations…";el("current-station-list").replaceChildren();
    sun();restore();load();
  });
  setInterval(sun,10000);
  setInterval(()=>{if(!document.hidden&&!el("current").hidden)load();},60000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!el("current").hidden){sun();load();}});
  restore();sun();
  return {select(id){if(id==="current")load();}};
})();
