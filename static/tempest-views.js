"use strict";
window.WeatherTempest=(()=>{
  const el=id=>document.getElementById(id),endpoint="/api/tempest",dirs=["N","NE","E","SE","S","SW","W","NW"];
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",second:"2-digit",timeZoneName:"short"});
  let data,active=false,busy=false;
  const finite=Number.isFinite;
  function age(stamp){return (Date.now()-Date.parse(stamp))/1000;}
  function windText(w={},summary=false){
    if(!finite(w.speedMph))return "—";
    if(summary&&Math.round(w.speedMph)<=3)return "CALM";
    if(w.speedMph<.5)return "Calm";
    const direction=w.variable?"Variable":w.cardinal||(finite(w.direction)?dirs[Math.round(w.direction/45)%8]:"Unknown");
    return `${direction} ${Math.round(w.speedMph)} mph`;
  }
  function render(){
    if(!active||!data)return;
    const s=data.summary,limit=data.maxReportAgeSeconds||600;
    const contributing=data.stations.filter(r=>r.included),current=contributing.filter(r=>finite(age(r.observedAt))&&age(r.observedAt)>=-90&&age(r.observedAt)<=limit);
    const usable=s.stationCount>0&&current.length===contributing.length;
    el("tempest-temperature").textContent=usable&&finite(s.tempF)?`${s.tempF}°F`:"—";
    el("tempest-dewpoint").textContent=usable&&finite(s.dewpointF)?`${s.dewpointF}°F`:"—";
    el("tempest-wind").textContent=usable?windText(s.wind,true):"—";
    el("tempest-count").textContent=`${current.length} / ${s.totalStations}`;
    let message=usable?`Reports ${clock.formatRange?clock.formatRange(new Date(s.oldestReportAt),new Date(s.newestReportAt)):clock.format(new Date(s.newestReportAt))}`:"Waiting for fresh station reports";
    message+=" · Checks every 5 min";
    if(data.checkedAt)message+=` · Checked ${clock.format(new Date(data.checkedAt))}`;
    if(data.stale)message+=" · Collector unavailable";
    if(data._savedCopy)message+=" · Saved";
    el("tempest-time").textContent=message;
    el("tempest-wind-count").textContent=usable&&s.wind.stationCount!==s.stationCount?`${s.wind.stationCount} wind reports`:"";
    const body=el("tempest-stations");body.replaceChildren();
    for(const station of data.stations){
      const row=document.createElement("tr"),name=document.createElement("td"),link=document.createElement("a"),id=document.createElement("small");
      link.textContent=station.name;link.href=station.url;link.target="_blank";link.rel="noopener";id.textContent=station.stationId;
      name.append(link,id);row.append(name);
      const stale=station.observedAt&&age(station.observedAt)>limit;
      for(const text of [station.observedAt?clock.format(new Date(station.observedAt)):"Unavailable",finite(station.tempF)?`${station.tempF.toFixed(1)}°F`:"—",finite(station.dewpointF)?`${station.dewpointF.toFixed(1)}°F`:"—",windText(station.wind),stale?"Stale":station.status]){
        const cell=document.createElement("td");cell.textContent=text;row.append(cell);
      }
      row.className=stale||!station.included?"tempest-excluded":"";body.append(row);
    }
  }
  function adopt(next){
    if(!next.summary||!Array.isArray(next.stations))throw Error("Tempest reports are not ready");
    if(data&&next.checkedAt<data.checkedAt)return;
    data=next;render();
  }
  async function load(force=false){
    if(busy)return;busy=true;el("refresh-tempest").disabled=true;
    try{adopt(await window.WeatherPrepared.read(endpoint,{force}));}
    catch(error){el("tempest-time").textContent=data?"Refresh unavailable · previous report times retained":error.message;}
    finally{busy=false;el("refresh-tempest").disabled=false;}
  }
  el("refresh-tempest").addEventListener("click",()=>load(true));
  window.WeatherPrepared.subscribe(endpoint,adopt);
  // This only reads prepared JSON. Browser collection runs privately every 5 min.
  setInterval(()=>{if(active&&!document.hidden)load(true);},60000);
  setInterval(()=>{if(active&&!document.hidden)render();},30000);
  return {select(id){active=id==="tempest";if(active){render();load();}},refresh(){if(active)load(true);}};
})();
