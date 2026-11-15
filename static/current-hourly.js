"use strict";
window.WeatherCurrent=(()=>{
  const el=id=>document.getElementById(id),endpoint="/api/current",dirs=["N","NE","E","SE","S","SW","W","NW"];
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let data,active=false,busy=false;
  const degrees=v=>Number.isFinite(v)?`${Math.round(v)}°F`:"—";
  function windText(w={},average=false){
    if(!Number.isFinite(w.speedMph))return "—";
    const speed=Math.round(w.speedMph);
    if(average?speed<=3:w.speedMph<.5)return "CALM";
    const direction=Number.isFinite(w.direction)?dirs[Math.round(w.direction/45)%8]:w.variable?"Variable":"Unknown";
    return `${direction} ${speed} mph`;
  }
  function appendRow(body,texts,incomplete=false){
    const row=document.createElement("tr");if(incomplete)row.className="current-incomplete";
    for(const text of texts){const cell=document.createElement("td");cell.textContent=text;row.append(cell);}body.append(row);
  }
  function render(){
    if(!active||!data)return;
    const latest=data.current;
    el("current-temperature").textContent=degrees(latest?.tempF);
    el("current-dewpoint").textContent=degrees(latest?.dewpointF);
    el("current-wind").textContent=windText(latest?.wind,true);
    let status=latest?`${clock.format(new Date(latest.hour))} · 3-airport average`:"Waiting for a complete three-airport hour";
    const currentHour=new Date();currentHour.setUTCMinutes(0,0,0);
    const pending=data.pendingHour||(!latest||Date.parse(latest.hour)<currentHour.getTime()?currentHour.toISOString():null);
    if(pending)status+=` · Waiting for ${clock.format(new Date(pending))} reports`;
    if(data.checkedAt)status+=` · Checked ${clock.format(new Date(data.checkedAt))}`;
    if(data._savedCopy)status+=" · Saved";
    el("current-time").textContent=status;
    const history=el("current-history");history.replaceChildren();
    for(const hour of data.history)appendRow(history,[clock.format(new Date(hour.hour)),degrees(hour.tempF),degrees(hour.dewpointF),windText(hour.wind,true),hour.complete?"3 / 3":"Incomplete"],!hour.complete);
    const stations=el("current-stations");stations.replaceChildren();
    for(const station of latest?.stations||[])appendRow(stations,[station.code,station.observedAt?clock.format(new Date(station.observedAt)):"Unavailable",degrees(station.tempF),degrees(station.dewpointF),windText(station.wind)]);
    if(window.WeatherSun)el("current-sun").textContent=`${Math.round(window.WeatherSun.elevation(new Date()))}°`;
  }
  function adopt(next){
    if(!Array.isArray(next.history)||next.history.length!==12)throw Error("Hourly METAR history is not ready");
    if(data&&next.checkedAt<data.checkedAt)return;
    data=next;render();
  }
  async function load(force=false){
    if(busy)return;busy=true;el("refresh-current").disabled=true;
    try{adopt(await window.WeatherPrepared.read(endpoint,{force}));}
    catch(error){if(!data)el("current-time").textContent=error.message;else{render();el("current-time").textContent+=" · Refresh unavailable";}}
    finally{busy=false;el("refresh-current").disabled=false;}
  }
  el("refresh-current").addEventListener("click",()=>load(true));
  window.WeatherPrepared.subscribe(endpoint,adopt);
  setInterval(()=>{if(active&&!document.hidden)load(true);},30000);
  setInterval(()=>{if(active&&!document.hidden)render();},10000);
  return {select(id){active=id==="current";if(active){render();load();}},refresh(){if(active)load(true);}};
})();
