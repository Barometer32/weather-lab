"use strict";
// Forecast shares Current's saved point; it never requests device location.
window.WeatherForecast = (()=>{
  const el=id=>document.getElementById(id),savedKey="weather-selected-forecast-v1";
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const pointKey=p=>`${p.latitude.toFixed(4)},${p.longitude.toFixed(4)}`;
  let data=null,busy=false,serial=0,error="",saved=false,queued=false,queuedForce=false;
  const location=()=>window.WeatherLocation.get();
  const matches=(next,p)=>Number.isFinite(next?.latitude)&&Number.isFinite(next?.longitude)&&pointKey(next)===pointKey(p);
  function place(){
    const p=location();el("forecast-location").textContent=p.label||data?.location||"Selected location";
    const link=el("forecast-source");
    link.href=`https://forecast.weather.gov/MapClick.php?lat=${p.latitude.toFixed(4)}&lon=${p.longitude.toFixed(4)}&unit=0&lg=english&FcstType=text&TextType=1`;
  }
  function render(){
    place();
    if(!data)return;
    const periods=data.periods.filter(p=>Date.parse(p.endTime)>Date.now());
    el("forecast-updated").textContent=`${saved?"Saved · ":""}NWS updated ${clock.format(new Date(data.updatedAt))}`;
    el("forecast-status").hidden=!error&&periods.length>0;
    el("forecast-status").textContent=error?`${error} Displayed forecast is the previous successful forecast for this same location.`:periods.length?"":"No current forecast periods remain. Please refresh.";
    el("forecast-periods").replaceChildren();
    for(const period of periods){
      const row=document.createElement("article");row.className="forecast-row";
      const name=document.createElement("h2");name.textContent=period.name;
      const temperature=document.createElement("div");temperature.className="forecast-temperature";
      const label=document.createElement("span");label.textContent=period.isDaytime?"High":"Low";
      const value=document.createElement("strong");value.textContent=period.temperature==null?"—":`${period.temperature}°${period.temperatureUnit||"F"}`;
      temperature.append(label,value);
      const detail=document.createElement("p");detail.className="forecast-detail";detail.textContent=period.detailedForecast;
      row.append(name,temperature,detail);el("forecast-periods").append(row);
    }
  }
  function restore(){
    try{
      const old=JSON.parse(localStorage.getItem(savedKey));
      if(old&&matches(old.data,location())&&Date.now()-old.storedAt<21600000&&old.data.periods.some(p=>Date.parse(p.endTime)>Date.now())){
        data=old.data;saved=true;render();
      }
    }catch(_){}
  }
  async function load(force=false){
    if(busy){queued=true;queuedForce=queuedForce||force;return;}
    const request=serial,p=location();busy=true;el("refresh-forecast").disabled=true;place();
    try{
      const response=await fetch("/api/forecast",{method:"POST",headers:{"Content-Type":"application/json"},cache:"no-store",body:JSON.stringify({latitude:Number(p.latitude.toFixed(4)),longitude:Number(p.longitude.toFixed(4)),force}),signal:AbortSignal.timeout(25000)});
      const next=await response.json();
      if(!response.ok)throw Error(next.error||"NWS forecast unavailable.");
      if(request!==serial)return;
      if(!matches(next,p)||!Array.isArray(next.periods)||!Number.isFinite(Date.parse(next.updatedAt)))throw Error("The forecast location could not be verified.");
      data=next;saved=false;error="";
      try{localStorage.setItem(savedKey,JSON.stringify({storedAt:Date.now(),data}));}catch(_){}
      render();
    }catch(problem){
      if(request!==serial)return;
      error=problem.message;saved=!!data;
      if(data)render();else{
        el("forecast-updated").textContent="";el("forecast-status").hidden=false;el("forecast-status").textContent=error;
      }
    }finally{
      busy=false;el("refresh-forecast").disabled=false;
      if(queued){const force=queuedForce;queued=false;queuedForce=false;load(force);}
    }
  }
  window.WeatherLocation.subscribe(()=>{
    serial++;data=null;error="";saved=false;
    try{localStorage.removeItem(savedKey);}catch(_){}
    el("forecast-periods").replaceChildren();el("forecast-updated").textContent="Loading the selected location’s NWS forecast…";
    el("forecast-status").hidden=true;place();load();
  });
  el("refresh-forecast").addEventListener("click",()=>load(true));
  setInterval(()=>{if(!document.hidden&&!el("forecast").hidden)load();},1800000);
  setInterval(()=>{if(!document.hidden&&!el("forecast").hidden)render();},30000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!el("forecast").hidden)load();});
  restore();place();load();
  return {select(id){if(id==="forecast")load();}};
})();
