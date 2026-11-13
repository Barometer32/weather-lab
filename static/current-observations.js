"use strict";
// Prepared Fahrenheit average of the approved Hennepin West station roster.
window.WeatherObservations = (()=>{
  const el=id=>document.getElementById(id),url="/api/observations/current";
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  let data,busy=false,error=null;
  const number=(value,unit,digits=0)=>Number.isFinite(value)?`${digits===0?Math.round(value):value.toFixed(digits)}${unit}`:"—";
  function stationDirection(station){
    if(!Number.isFinite(station.windSpeedMph))return "—";
    if(station.windSpeedMph===0)return "Calm";
    if(station.windVariable)return "Variable";
    const bearing=station.windDirection;
    return Number.isFinite(bearing)&&bearing>=0&&bearing<=360?directions[Math.round(bearing/45)%8]:"—";
  }
  function render(){
    if(el("observations").hidden)return;
    const now=Date.now(),value=data?.current,maxAge=(data?.maxAgeSeconds||1800)*1000;
    const oldest=Date.parse(value?.oldestObservedAt),newest=Date.parse(value?.observedAt);
    const valid=value&&newest<=now&&oldest<=newest&&now-oldest<=maxAge;
    el("observations-temperature").textContent=valid?number(value.temperatureF,"°F"):"—";
    el("observations-dewpoint").textContent=valid?number(value.dewpointF,"°F"):"—";
    el("observations-wind").textContent=valid&&Number.isFinite(value.windSpeedMph)?value.windCardinal==="Calm"?"Calm":`${value.windCardinal||""} ${number(value.windSpeedMph," mph")}`.trim():"—";
    const age=valid?Math.max(0,Math.floor((now-oldest)/60000)):null;
    const delayed=data?.stale||data?.checkedAt&&now-Date.parse(data.checkedAt)>660000;
    const partial=valid&&Object.entries(value.sampleCounts||{}).some(([key,count])=>key!=="windDirection"&&count<data.expectedStationCount);
    const status=error?" · Refresh failed":delayed?" · Collection delayed":age>15?" · Source delayed":partial?" · Partial coverage":data?._savedCopy?" · Saved":"";
    const range=valid?`${clock.format(new Date(oldest))}${oldest===newest?"":" – "+clock.format(new Date(newest))}`:"";
    el("observations-time").textContent=valid?`${range} · ${value.stationCount}/${data.expectedStationCount} stations · oldest ${age}m${status}`:busy?"Loading Hennepin West observations…":error?"Observations unavailable · try Refresh":"Waiting for recent approved Hennepin West reports";
    el("observations-time").title=data?.checkedAt?`Feed checked ${clock.format(new Date(data.checkedAt))}. The displayed range uses actual station report times.`:"";
    const counts=value?.sampleCounts;
    el("observations-counts").textContent=valid&&counts?`Contributing stations: temperature ${counts.temperature}/${data.expectedStationCount}, dewpoint ${counts.dewpoint}/${data.expectedStationCount}, wind speed ${counts.windSpeed}/${data.expectedStationCount}; ${counts.windDirection} non-calm bearings used for direction.`:"";
    const body=el("observations-stations");body.replaceChildren();
    for(const station of data?.stations||[]){
      const row=document.createElement("tr");
      for(const text of [`${station.displayName} (${station.station})`,clock.format(new Date(station.time)),number(station.tempF,"°F",1),number(station.dewpointF,"°F",1),stationDirection(station),number(station.windSpeedMph," mph")]){
        const cell=document.createElement("td");cell.textContent=text;row.append(cell);
      }
      body.append(row);
    }
  }
  function adopt(next){
    if(next?.version!=="hennepin-west-average-v1"||next.temperatureBasis!=="reported-Fahrenheit"||next.stationPolicy!=="approved-hennepin-west-19-v1")throw Error("Unexpected Mesonet observation data");
    if(data&&(Date.parse(next.checkedAt)<Date.parse(data.checkedAt)||next._savedCopy&&!data._savedCopy))return;
    data=next;error=null;
    if(next.serverTime&&!next._savedCopy)window.WeatherSun?.sync(next.serverTime);
    render();
  }
  async function load(force=false){
    if(busy)return;busy=true;el("refresh-observations").disabled=true;
    try{adopt(await window.WeatherPrepared.read(url,{force}));}catch(e){error=e.message;}
    finally{busy=false;el("refresh-observations").disabled=false;render();}
  }
  window.WeatherPrepared.subscribe(url,adopt);
  el("refresh-observations").addEventListener("click",()=>load(true));
  setInterval(()=>{if(!document.hidden&&!el("observations").hidden){render();load();}},15000);
  return {select(id){if(id==="observations"){render();load();}},refresh(){render();load();}};
})();
