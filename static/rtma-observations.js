"use strict";
window.WeatherRTMA = (() => {
  const endpoint="/api/observations/rtma", byId=id=>document.getElementById(id);
  const timeFormat=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  let data=null,busy=false,error=null;
  const whole=value=>Number.isFinite(value)?String(Math.round(value)):"—";
  const temperature=value=>Number.isFinite(value)?`${whole(value)}°F`:"—";
  function wind(value){
    if(!value||!Number.isFinite(value.speedMph))return "—";
    if(value.speedMph<.5)return "Calm";
    const direction=Number.isFinite(value.direction)?directions[Math.round(((value.direction%360)+360)%360/45)%8]:"Variable";
    return `${direction} ${whole(value.speedMph)} mph`;
  }
  function sun(){
    if(!data||!window.WeatherSun)return;
    const now=new Date(),angles=data.stations.map(station=>window.WeatherSun.elevation(now,station.lat,station.lon));
    byId("rtma-sun").textContent=`${whole(angles.reduce((a,b)=>a+b,0)/angles.length)}°`;
  }
  function render(){
    if(!data)return;
    const age=Math.max(0,Math.floor((Date.now()-Date.parse(data.analysisTime))/60000));
    const checkedAge=Math.max(0,(Date.now()-Date.parse(data.checkedAt))/60000);
    byId("rtma-time").textContent=`${data._savedCopy?"Saved · ":""}Analysis ${timeFormat.format(new Date(data.analysisTime))} · ${age} min old · 3 locations`;
    byId("rtma-temp").textContent=temperature(data.mean.tempF);
    byId("rtma-dewpoint").textContent=temperature(data.mean.dewpointF);
    byId("rtma-wind").textContent=wind(data.mean.wind);
    byId("rtma-status").textContent=error?`${error} Keeping the previous analysis and its original time.`:
      checkedAge>5?"Background checks are delayed; the actual analysis time is shown.":
      age>45?"NOAA analysis updates are delayed; the last complete cycle is shown.":"";
    byId("rtma-stations").replaceChildren();
    for(const station of data.stations){
      const row=document.createElement("tr");
      for(const text of [station.station,timeFormat.format(new Date(station.analysisTime)),temperature(station.tempF),temperature(station.dewpointF),wind(station.wind)]){
        const cell=document.createElement("td");cell.textContent=text;row.append(cell);
      }
      row.title=`${station.name}: nearest grid point ${station.gridLat.toFixed(4)}, ${station.gridLon.toFixed(4)}; ${station.gridDistanceKm.toFixed(1)} km from the airport coordinate.`;
      byId("rtma-stations").append(row);
    }
    byId("rtma-checked").textContent=`Last successful source check: ${timeFormat.format(new Date(data.checkedAt))}. New analyses every 15 minutes; checked every minute.`;
    sun();
  }
  async function refresh(force=true){
    if(busy)return;
    busy=true;byId("refresh-rtma").disabled=true;
    try{
      data=await window.WeatherPrepared.read(endpoint,{force});error=null;render();
    }catch(problem){
      error=problem.message||"The RTMA-RU analysis could not be refreshed.";
      if(data)render();
      else {byId("rtma-time").textContent="Waiting for the first complete RTMA-RU analysis";byId("rtma-status").textContent=error;}
    }finally{busy=false;byId("refresh-rtma").disabled=false;}
  }
  function select(id){if(id==="observations"){render();refresh(false);}}
  byId("refresh-rtma").addEventListener("click",()=>refresh(true));
  window.WeatherPrepared.subscribe(endpoint,fresh=>{data=fresh;error=null;render();});
  setInterval(()=>{if(!document.hidden&&!byId("observations").hidden)refresh(true);},15000);
  setInterval(()=>{if(!document.hidden&&!byId("observations").hidden)render();},10000);
  return {select,refresh,wind};
})();
