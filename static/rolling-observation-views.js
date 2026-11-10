"use strict";
window.WeatherRollingObservations = (() => {
  const el=id=>document.getElementById(id),url="/api/observations/mesonet";
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const compass=["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
  let data,busy=false,error;
  const formatTime=stamp=>time.format(new Date(stamp));
  const degrees=value=>Number.isFinite(value)?`${value}°F`:"—";
  function windText(wind){
    if(!Number.isFinite(wind?.speedMph))return "—";
    if(wind.speedMph===0)return "Calm";
    const dir=Number.isFinite(wind.direction)?compass[Math.round(wind.direction/22.5)%16]:wind.variable?"Variable":"";
    return `${dir?dir+" ":""}${wind.speedMph} mph`;
  }
  function render(){
    if(el("observations").hidden)return;
    const current=data?.current;
    const cutoff=Date.parse(current?.oldestObservedAt)+data?.windowMinutes*60000;
    const recent=Number.isFinite(cutoff)&&Date.now()<=cutoff?current:null;
    const status=recent?`Hennepin West Mesonet · Updated from reports through ${formatTime(current.observedAt)} · ${current.stationIds.length}/${data.stationCount} stations${error||data.delayed||data._savedCopy?" · update delayed":""}`:
      !data&&busy?"Loading Hennepin West Mesonet observations…":
      error||"Waiting for recent Hennepin West Mesonet reports";
    el("rolling-observation-time").textContent=status;
    el("observations-temperature").textContent=degrees(recent?.tempF);
    el("observations-dewpoint").textContent=degrees(recent?.dewpointF);
    el("observations-wind").textContent=windText(recent?.wind);
  }
  function adopt(next){
    if(next===data||!Object.hasOwn(next??{},"current")||next._savedCopy&&data&&!data._savedCopy)return;
    data=next;error=null;
    if(!el("observations").hidden&&next.serverTime&&!next._savedCopy)window.WeatherSun?.sync(next.serverTime);
    render();
  }
  async function load(force=false){
    if(busy)return;
    busy=true;el("refresh-observations").disabled=true;
    try{adopt(await window.WeatherPrepared.read(url,{force}));}
    catch(err){error=err.message;}
    finally{busy=false;el("refresh-observations").disabled=false;render();}
  }
  window.WeatherPrepared.subscribe(url,adopt);
  el("refresh-observations").addEventListener("click",()=>load(true));
  setInterval(()=>{if(!document.hidden&&!el("observations").hidden)load();},30000);
  return {select(id){if(id==="observations"){load();render();}}};
})();
