"use strict";
window.WeatherHourlyObservations = (() => {
  const el=id=>document.getElementById(id),url="/api/observations/hourly";
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const compass=["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
  let data,busy=false,error;
  const formatTime=stamp=>time.format(new Date(stamp));
  const degrees=value=>Number.isFinite(value)?`${value.toFixed(0)}°F`:"—";
  function windText(wind){
    if(!Number.isFinite(wind?.speedMph))return "—";
    const speed=wind.speedMph.toFixed(0);
    if(speed==="0")return "Calm";
    const direction=Number.isFinite(wind.direction)?compass[Math.round(wind.direction/22.5)%16]:wind.variable?"Variable":"";
    return `${direction?direction+" ":""}${speed} mph`;
  }
  function renderHistory(){
    const rows=(data?.history||[]).filter(hour=>hour.complete).map(hour=>{
      const row=document.createElement("tr");
      const values=[formatTime(hour.hour),degrees(hour.tempF),degrees(hour.dewpointF),
        windText(hour.wind)];
      values.forEach((value,index)=>{
        const cell=document.createElement(index?"td":"th");
        if(!index)cell.scope="row";
        cell.textContent=value;
        row.append(cell);
      });
      return row;
    });
    el("hourly-observation-history").replaceChildren(...rows);
  }
  function render(){
    if(el("observations").hidden)return;
    const pending=data?.pendingHour;
    let status=pending?`Waiting for the ${formatTime(pending)} reports.`:
      !data&&busy?"Loading hourly airport observations…":"";
    if(error||data?._savedCopy)status=[status,"Update delayed."].filter(Boolean).join(" ");
    const notice=el("hourly-observation-time");
    notice.textContent=status;
    notice.hidden=!status;
  }
  function adopt(next){
    if(next===data||!Array.isArray(next?.history)||next._savedCopy&&data&&!data._savedCopy)return;
    data=next;error=null;
    if(!el("observations").hidden&&next.serverTime&&!next._savedCopy)window.WeatherSun?.sync(next.serverTime);
    renderHistory();
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
  setInterval(()=>{if(!document.hidden&&!el("observations").hidden)load();},60000);
  return {select(id){if(id==="observations"){load();render();}}};
})();
