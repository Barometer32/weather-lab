"use strict";
// Prepared three-airport average. Sun angle uses the current clock separately.
window.WeatherObservations = (()=>{
  const el=id=>document.getElementById(id),url="/api/observations/current";
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let data,busy=false,error=null;
  const number=(value,unit)=>Number.isFinite(value)?`${value.toFixed(1)}${unit}`:"—";
  function render(){
    if(el("observations").hidden)return;
    const now=Date.now(),value=data?.current;
    const valid=value&&Date.parse(value.observedAt)<=now&&now-Date.parse(value.observedAt)<=3600000;
    el("observations-temperature").textContent=valid?number(value.temperatureF,"°F"):"—";
    el("observations-temperature-c").textContent=valid?number(value.temperatureC,"°C"):"";
    el("observations-dewpoint").textContent=valid?number(value.dewpointF,"°F"):"—";
    el("observations-dewpoint-c").textContent=valid?number(value.dewpointC,"°C"):"";
    el("observations-wind").textContent=valid?number(value.windSpeedMph," mph"):"—";
    const age=valid?Math.max(0,Math.floor((now-Date.parse(value.observedAt))/60000)):null;
    const delayed=data?.stale||data?.checkedAt&&now-Date.parse(data.checkedAt)>600000;
    const status=error?" · Refresh failed":delayed?" · Collection delayed":age>15?" · Source delayed":data?.waiting?" · Waiting for matching reports":data?._savedCopy?" · Saved":"";
    el("observations-time").textContent=valid?`${clock.format(new Date(value.observedAt))} · ${age}m old · 3 airports${status}`:busy?"Loading five-minute observations…":error?"Observations unavailable · try Refresh":"Waiting for complete matching five-minute reports from all three airports";
    el("observations-time").title=data?.checkedAt?`Feed checked ${clock.format(new Date(data.checkedAt))}. All three reports use the displayed observation time.`:"";
    const body=el("observations-stations");body.replaceChildren();
    for(const station of valid?value.stations:data?.stations||[]){
      const row=document.createElement("tr");
      for(const text of [station.station,clock.format(new Date(station.time)),number(station.tempC,"°C"),number(station.dewpointC,"°C"),number(station.windSpeedMph," mph")]){
        const cell=document.createElement("td");cell.textContent=text;row.append(cell);
      }
      row.title=station.rawOb||"";body.append(row);
    }
  }
  function adopt(next){
    if(next?.version!=="three-airport-rapid-main-c-v1"||next.temperatureBasis!=="main-XX/XX")throw Error("Unexpected observation data");
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
  setInterval(()=>{if(!document.hidden&&!el("observations").hidden){render();load();}},30000);
  return {select(id){if(id==="observations"){render();load();}},refresh(){render();load();}};
})();
