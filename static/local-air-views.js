"use strict";
window.WeatherLocalAir=(()=>{
  const el=id=>document.getElementById(id),storageKey="weather-local-air-v2";
  const pollutants={"PM2.5":"pm25","PM10":"pm10","Ozone":"ozone","NO2":"no2"};
  const pointKey=p=>`${p.latitude.toFixed(4)},${p.longitude.toFixed(4)}`;
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let data=null,busy=false,serial=0,queued=false,saved=false,error="";
  const fresh=stamp=>Number.isFinite(Date.parse(stamp))&&Date.now()-Date.parse(stamp)<=10800000&&Date.parse(stamp)<=Date.now();
  const color=n=>!Number.isFinite(n)?"#77837d":n<=50?"#00a82d":n<=100?"#ad8500":n<=150?"#dd6500":n<=200?"#d42626":n<=300?"#8f3f97":"#7e0023";
  function clear(){
    for(const code of Object.values(pollutants)){
      el(`air-${code}-value`).textContent="—";el(`air-${code}-aqi`).textContent="";
      el(`air-${code}-source`).textContent="Nearest available monitor";el(`air-${code}-time`).textContent="";
      el(`air-${code}-card`).style.setProperty("--air-color","#77837d");
    }
    el("local-air-inputs").replaceChildren();
  }
  function render(){
    if(!data)return;
    const list=el("local-air-inputs");list.replaceChildren();let available=false;
    for(const [name,code] of Object.entries(pollutants)){
      const row=(data.readings||[]).find(r=>r.pollutant===name),r=row&&fresh(row.time)?row:null;
      available=available||!!(r&&(Number.isFinite(r.value)||Number.isFinite(r.aqi)));
      el(`air-${code}-value`).textContent=Number.isFinite(r?.value)?r.value.toFixed(1):"—";
      el(`air-${code}-aqi`).textContent=Number.isFinite(r?.aqi)?`${r.aqiType} ${r.aqi}`:"AQI unavailable";
      el(`air-${code}-card`).style.setProperty("--air-color",color(r?.aqi));
      el(`air-${code}-source`).textContent=r?.station?`${r.station} · ${(r.distanceKm*.621371).toFixed(1)} mi`:"Unavailable within 50 km";
      el(`air-${code}-time`).textContent=r?.time?`${saved?"Saved · ":""}${clock.format(new Date(r.time))}`:"";
      if(r){
        const source=document.createElement("p");source.textContent=`${name}: ${r.station} (${r.stationId}) · ${r.distanceKm.toFixed(1)} km · hourly sample ${clock.format(new Date(r.start))}–${clock.format(new Date(r.time))}`;list.append(source);
      }
    }
    const status=error||data.message||(data.stale?"Air quality updates are delayed. Check the source times.":!available?"Recent pollutant observations are unavailable.":"");
    el("local-air-status").textContent=status;el("local-air-status").hidden=!status;
  }
  async function load(){
    if(busy){queued=true;return;}busy=true;
    const request=serial,p=window.WeatherLocation.get();if(data)render();
    el("refresh-local-air").disabled=true;
    try{
      const response=await fetch("/api/local-air-quality",{method:"POST",headers:{"Content-Type":"application/json"},cache:"no-store",body:JSON.stringify({latitude:Number(p.latitude.toFixed(4)),longitude:Number(p.longitude.toFixed(4))}),signal:AbortSignal.timeout(55000)});
      const next=await response.json();if(!response.ok)throw Error(next.error||"Air quality unavailable.");
      if(request!==serial)return;
      if(next.version!=="local-pollutants-v2"||!Number.isFinite(next.latitude)||!Number.isFinite(next.longitude)||pointKey(next)!==pointKey(p))throw Error("Air quality location or version could not be verified.");
      data=next;saved=false;error="";
      try{localStorage.setItem(storageKey,JSON.stringify({point:pointKey(p),storedAt:Date.now(),data}));}catch(_){}
      render();
    }catch(problem){
      if(request!==serial)return;
      error=problem.message;saved=!!data;
      if(data)render();else{el("local-air-status").hidden=false;el("local-air-status").textContent=error;}
    }finally{
      busy=false;el("refresh-local-air").disabled=false;
      if(queued){queued=false;load();}
    }
  }
  try{
    localStorage.removeItem("weather-local-air-v1");
    const old=JSON.parse(localStorage.getItem(storageKey));
    if(old?.point===pointKey(window.WeatherLocation.get())&&old.data?.version==="local-pollutants-v2"&&Date.now()-old.storedAt<10800000){data=old.data;saved=true;render();}
  }catch(_){}
  window.WeatherLocation.subscribe(()=>{
    serial++;data=null;saved=false;error="";clear();
    try{localStorage.removeItem(storageKey);}catch(_){}
    el("local-air-status").hidden=false;el("local-air-status").textContent="Loading pollutants for the selected location…";
    load();
  });
  el("refresh-local-air").addEventListener("click",load);
  setInterval(()=>{if(!document.hidden&&!el("current").hidden)load();},1800000);
  setInterval(()=>{if(!document.hidden&&!el("current").hidden)render();},60000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!el("current").hidden)load();});
  load();
  return {select(id){if(id==="current"){render();if(!busy&&(!data||Date.now()-Date.parse(data.checkedAt)>1800000))load();}}};
})();
