"use strict";
window.WeatherCurrent=(()=>{
  const el=id=>document.getElementById(id),endpoint="/api/current",dirs=["N","NE","E","SE","S","SW","W","NW"];
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let data,active=false,busy=false;
  const degrees=v=>Number.isFinite(v)?`${Math.round(v)}°F`:"—";
  function windText(w={},average=false){
    if(!Number.isFinite(w.speedMph))return "—";
    const speed=Math.round(w.speedMph);
    if(average?speed<=3:w.speedMph<.5)return "CALM";
    const direction=Number.isFinite(w.direction)?dirs[Math.round(w.direction/45)%8]:w.variable?"Variable":"Unknown";
    return `${direction} ${speed}`;
  }
  function appendRow(body,texts){
    const row=document.createElement("tr");
    for(const text of texts){const cell=document.createElement("td");cell.textContent=text;row.append(cell);}body.append(row);
  }
  function render(){
    if(!active||!data)return;
    const latest=data.current;
    el("current-temperature").textContent=degrees(latest?.tempF);
    el("current-dewpoint").textContent=degrees(latest?.dewpointF);
    el("current-wind").textContent=windText(latest?.wind,true);
    el("current-time").textContent=latest?clock.format(new Date(latest.hour)):"—";
    const history=el("current-history");history.replaceChildren();
    for(const hour of data.history)if(hour.complete)appendRow(history,[clock.format(new Date(hour.hour)),degrees(hour.tempF),degrees(hour.dewpointF),windText(hour.wind,true)]);
    window.WeatherSun?.update?.();
  }
  function adopt(next){
    if(!Array.isArray(next.history)||next.history.length>12)throw Error("Hourly METAR history is not ready");
    if(data&&next.checkedAt<data.checkedAt)return;
    data=next;render();
  }
  async function load(force=false){
    if(busy)return;busy=true;el("refresh-current").disabled=true;
    try{adopt(await window.WeatherPrepared.read(endpoint,{force}));}
    catch(error){if(!data)el("current-time").textContent=error.message;else render();}
    finally{busy=false;el("refresh-current").disabled=false;}
  }
  el("refresh-current").addEventListener("click",()=>load(true));
  window.WeatherPrepared.subscribe(endpoint,adopt);
  setInterval(()=>{if(active&&!document.hidden)load(true);},30000);
  setInterval(()=>{if(active&&!document.hidden)render();},10000);
  return {select(id){active=id==="current";if(active){window.WeatherSun?.update?.();render();load();}},refresh(){if(active)load(true);}};
})();
