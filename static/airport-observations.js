"use strict";
window.WeatherAirportObservations=(()=>{
  const el=id=>document.getElementById(id),endpoint="/api/airport-observations";
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  let data,active=false,busy=false;
  const finite=Number.isFinite;
  function windText(w={},summary=false){
    if(!finite(w.speedMph))return "Unavailable";
    if(summary&&Math.round(w.speedMph)<=3)return "CALM";
    if(w.speedMph<.5)return "Calm";
    const direction=w.variable?"Variable":w.cardinal||(finite(w.direction)?directions[Math.round(w.direction/45)%8]:"Unknown");
    return `${direction} ${Math.round(w.speedMph)} mph`;
  }
  function render(){
    if(!active||!data)return;
    const current=data.current,age=current?Math.max(0,Math.floor((Date.now()-Date.parse(current.observedAt))/60000)):null;
    el("observations-time").textContent=current?`${time.format(new Date(current.observedAt))} · ${age} min old · 3 airports${data.stale?" · Collector delayed":""}${data._savedCopy?" · Saved":""}`:"Waiting for matching five-minute reports from all three airports";
    for(const [id,key] of [["observations-temperature","tempF"],["observations-dewpoint","dewpointF"]])el(id).textContent=finite(current?.[key])?`${current[key]}°F`:"—";
    el("observations-wind").textContent=current?windText(current.wind,true):"—";
    const body=el("observations-stations");body.replaceChildren();
    for(const s of data.stations||[]){
      const row=document.createElement("tr");
      for(const value of [s.station,time.format(new Date(s.time)),finite(s.tempC)?`${Math.round(s.tempC)}°C`:"Unavailable",finite(s.dewpointC)?`${Math.round(s.dewpointC)}°C`:"Unavailable",windText(s.wind)]){
        const cell=document.createElement("td");cell.textContent=value;row.append(cell);
      }
      body.append(row);
    }
  }
  function adopt(next){
    if(!Array.isArray(next.stations))throw Error("The airport observations are not ready");
    if(data&&next.checkedAt<data.checkedAt)return;
    data=next;if(next.serverTime&&!next._savedCopy)window.WeatherSun?.sync(next.serverTime);render();
  }
  async function load(force=false){
    if(busy)return;busy=true;el("refresh-observations").disabled=true;
    try{adopt(await window.WeatherPrepared.read(endpoint,{force}));}
    catch(e){el("observations-time").textContent=data?el("observations-time").textContent+" · Refresh unavailable":e.message;}
    finally{busy=false;el("refresh-observations").disabled=false;}
  }
  el("refresh-observations").addEventListener("click",()=>load(true));
  window.WeatherPrepared.subscribe(endpoint,adopt);
  setInterval(()=>{if(active&&!document.hidden)load(true);},300000);
  setInterval(()=>{if(active&&!document.hidden)render();},60000);
  return {select(id){active=id==="observations";if(active){render();load();}},refresh(){if(active)load(true);}};
})();
