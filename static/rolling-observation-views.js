"use strict";
window.WeatherRollingObservations = (() => {
  const el=id=>document.getElementById(id),url="/api/observations/rolling";
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
    const reading=data?.current,t=Date.parse(reading?.observedAt);
    const current=Number.isFinite(t)&&Date.now()-t<=1800000?reading:null;
    const last=data?.lastCompleteAt;
    const status=current?`Observed ${formatTime(current.observedAt)} · all 3 airports${error||data._savedCopy?" · update delayed":""}`:
      !data&&busy?"Loading three-airport observations…":
      last?`No matched observation in the last 30 minutes · last match ${formatTime(last)}`:
      error||"Waiting for all 3 airports to report at the same time";
    el("rolling-observation-time").textContent=status;
    el("observations-temperature").textContent=degrees(current?.tempF);
    el("observations-dewpoint").textContent=degrees(current?.dewpointF);
    el("observations-wind").textContent=windText(current?.wind);
    const rows=(data?.history||[]).map(slot=>{
      const row=document.createElement("tr"),heading=document.createElement("th");
      heading.scope="row";heading.textContent=formatTime(slot.time);row.append(heading);
      for(const value of [degrees(slot.reading?.tempF),degrees(slot.reading?.dewpointF),windText(slot.reading?.wind)]){
        const cell=document.createElement("td");cell.textContent=value;row.append(cell);
      }
      return row;
    });
    el("rolling-observation-history").replaceChildren(...rows);
  }
  function adopt(next){
    if(next===data||!Array.isArray(next?.history)||next._savedCopy&&data&&!data._savedCopy)return;
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
