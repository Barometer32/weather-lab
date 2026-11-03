"use strict";
window.WeatherLocalAir=(()=>{
  const el=id=>document.getElementById(id),storageKey="weather-local-air-v1";
  const pointKey=p=>`${p.latitude.toFixed(4)},${p.longitude.toFixed(4)}`;
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const colors={Low:"#2179a4",Moderate:"#ad8500",High:"#cf4b32","Very high":"#7e1838"};
  let data=null,busy=false,serial=0,queued=false,saved=false,error="";
  const fresh=stamp=>Number.isFinite(Date.parse(stamp))&&Date.now()-Date.parse(stamp)<=10800000&&Date.parse(stamp)<=Date.now();
  function clear(){
    for(const id of ["local-aqi-value","local-mix-value"])el(id).textContent="—";
    for(const id of ["local-aqi-category","local-mix-category","local-aqi-time","local-mix-time","local-air-pollutants","local-air-area"])el(id).textContent="";
    el("local-air-inputs").replaceChildren();
  }
  function render(){
    if(!data)return;
    const a=data.aqi&&fresh(data.aqi.time)?data.aqi:null,m=data.mix&&fresh(data.mix.end)?data.mix:null;
    el("local-aqi-value").textContent=a?String(a.value):"—";
    el("local-aqi-category").textContent=a?a.category:"Unavailable";
    el("local-aqi-card").style.setProperty("--air-color",a?.color||"#77837d");
    el("local-aqi-time").textContent=a?`${saved?"Saved · ":""}${clock.format(new Date(a.time))}`:"";
    el("local-mix-value").textContent=m?m.display:"—";
    el("local-mix-category").textContent=m?`${m.category} · 1–10+ scale`:"Unavailable";
    el("local-mix-card").style.setProperty("--air-color",colors[m?.category]||"#77837d");
    el("local-mix-time").textContent=m?`${saved?"Saved · ":""}Through ${clock.format(new Date(m.end))}`:"";
    el("local-air-area").textContent=a?`U.S. AQI reporting area · ${a.area}, ${a.state}`:"No recent reporting-area AQI available.";
    el("local-air-pollutants").textContent=a?(a.pollutants||[]).map(p=>`${p.pollutant} AQI ${p.aqi}`).join(" · "):"";
    const status=error||data.message||(data.stale?"Air quality updates are delayed. Check the source times.":!a&&!m?"Recent air quality observations are unavailable.":!m?(data.mixMessage||"The combined estimate has expired."):"");
    el("local-air-status").textContent=status||"";el("local-air-status").hidden=!status;
    const list=el("local-air-inputs");list.replaceChildren();
    for(const r of (m?data.components:[])||[]){
      const article=document.createElement("article");article.className="contributor";
      const name=document.createElement("strong");name.textContent=`${r.pollutant} · ${r.mean.toFixed(1)} ${r.unit} (3-hour mean)`;
      const source=document.createElement("p");source.textContent=`${r.station} · ${(r.distanceKm*.621371).toFixed(1)} mi`;
      const weight=document.createElement("p");weight.textContent=`${data.mix?.contributionsPct?.[r.pollutant]??"—"}% of calculated mix score`;
      article.append(name,source,weight);list.append(article);
    }
    for(const r of data.readings||[]){
      if(!fresh(r.time))continue;
      const row=document.createElement("p");row.textContent=`Latest ${r.pollutant}: ${r.value.toFixed(1)} ${r.unit} · ${r.station} · ${clock.format(new Date(r.time))}`;list.append(row);
    }
  }
  async function load(){
    if(busy){queued=true;return;}busy=true;
    const request=serial,p=window.WeatherLocation.get();if(data)render();
    el("refresh-local-air").disabled=true;
    try{
      const response=await fetch("/api/local-air-quality",{method:"POST",headers:{"Content-Type":"application/json"},cache:"no-store",body:JSON.stringify({latitude:Number(p.latitude.toFixed(4)),longitude:Number(p.longitude.toFixed(4))}),signal:AbortSignal.timeout(65000)});
      const next=await response.json();if(!response.ok)throw Error(next.error||"Air quality unavailable.");
      if(request!==serial)return;
      if(!Number.isFinite(next.latitude)||!Number.isFinite(next.longitude)||pointKey(next)!==pointKey(p))throw Error("Air quality location could not be verified.");
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
    const old=JSON.parse(localStorage.getItem(storageKey));
    if(old?.point===pointKey(window.WeatherLocation.get())&&Date.now()-old.storedAt<10800000){data=old.data;saved=true;render();}
  }catch(_){}
  window.WeatherLocation.subscribe(()=>{
    serial++;data=null;saved=false;error="";clear();
    try{localStorage.removeItem(storageKey);}catch(_){}
    el("local-air-status").hidden=false;el("local-air-status").textContent="Loading air quality for the selected location…";
    load();
  });
  el("refresh-local-air").addEventListener("click",load);
  setInterval(()=>{if(!document.hidden&&!el("current").hidden)load();},1800000);
  setInterval(()=>{if(!document.hidden&&!el("current").hidden)render();},60000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!el("current").hidden)load();});
  load();
  return {select(id){if(id==="current"){render();if(!busy&&(!data||Date.now()-Date.parse(data.checkedAt)>1800000))load();}}};
})();
