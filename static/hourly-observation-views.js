"use strict";
window.WeatherHourlyObservations = (() => {
  const el=id=>document.getElementById(id),url="/api/observations/hourly";
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const compass=["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
  let data,busy=false,error;
  const formatTime=stamp=>time.format(new Date(stamp));
  const degrees=value=>Number.isFinite(value)?`${value.toFixed(1)}°F`:"—";
  function windText(wind){
    if(!Number.isFinite(wind?.speedMph))return "—";
    if(wind.speedMph===0)return "Calm";
    const direction=Number.isFinite(wind.direction)?compass[Math.round(wind.direction/22.5)%16]:wind.variable?"Variable":"";
    return `${direction?direction+" ":""}${wind.speedMph} mph`;
  }
  function renderHistory(){
    const rows=(data?.history||[]).map(hour=>{
      const row=document.createElement("tr");
      const values=[formatTime(hour.hour),degrees(hour.tempF),degrees(hour.dewpointF),
        windText(hour.wind),`${hour.count}/${data.stationCount}`];
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
    const current=data?.current;
    const pending=current&&data.history[0].hour!==current.hour;
    let status=current?`${formatTime(current.hour)} · ${current.count}/${data.stationCount} airports`:
      !data&&busy?"Loading hourly airport observations…":"Waiting for all three airports to report";
    if(pending)status+=" · New hour pending";
    if(error||data?._savedCopy)status+=" · Update delayed";
    el("hourly-observation-time").textContent=status;
    el("observations-temperature").textContent=degrees(current?.tempF);
    el("observations-dewpoint").textContent=degrees(current?.dewpointF);
    el("observations-wind").textContent=windText(current?.wind);
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
