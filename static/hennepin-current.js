"use strict";
window.WeatherHennepinCurrent = (()=>{
  const el=id=>document.getElementById(id),endpoint="/api/hennepin-current";
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const shortTime=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric",minute:"2-digit"});
  let data,busy=false,failed=false;
  const temp=v=>Number.isFinite(v)?`${v.toFixed(1)}°F`:"—";
  function wind(w){
    if(!Number.isFinite(w?.speedMph))return "—";
    if(w.speedMph<.5)return "0";
    const dir=Number.isFinite(w.direction)?["N","NE","E","SE","S","SW","W","NW"][Math.round(w.direction/45)%8]:"VRB";
    return `${dir} ${Math.round(w.speedMph)}`;
  }
  function render(){
    if(!data)return;
    const c=data.current;
    el("current-temp").textContent=temp(c?.tempF);el("current-dew").textContent=temp(c?.dewpointF);el("current-wind").textContent=wind(c?.wind);
    el("current-time").textContent=c?`${data._savedCopy?"Saved · ":""}Average observation: ${time.format(new Date(c.observedAt))}`:"Waiting for the selected station average…";
    const old=c&&Date.now()-Date.parse(c.observedAt)>45*60000;
    const delayed=data.held||data.collectorDelayed||old||failed||data.sourceFailures?.length;
    const notice=el("current-notice");notice.textContent=!c?"Waiting for enough aligned, usable station measurements.":delayed?"Updates delayed · showing the last usable average.":"";notice.hidden=!notice.textContent;
    if(el("current-details").open)renderStations();
  }
  function renderStations(){
    if(!data)return;
    const rows=el("current-station-rows");rows.replaceChildren();
    for(const s of data.candidate?.stations||[]){
      const tr=document.createElement("tr"),name=document.createElement("td"),label=document.createElement("span"),id=document.createElement("small");
      label.textContent=s.displayName;id.textContent=s.station;name.append(label,id);tr.append(name);
      const used=s.includedFields||[],missing=Object.values(s.reasons||{}),warnings=s.warnings||[];
      const status=used.length===3?"Included":used.length?`Partial: ${used.map(k=>({tempF:"temperature",dewpointF:"dewpoint",wind:"wind"}[k])).join(", ")}`:"Not included";
      const detail=[...new Set([...missing,...warnings])].join("; ");
      for(const value of [s.time?shortTime.format(new Date(s.time)):"—",temp(s.tempF).replace("°F",""),temp(s.dewpointF).replace("°F",""),wind(s.wind),(data.held?"Latest report; average held · ":"")+status+(detail?" · "+detail:"")]){
        const td=document.createElement("td");td.textContent=value;tr.append(td);
      }
      rows.append(tr);
    }
  }
  function adopt(next){
    if(next.version!=="hennepin-selected-twelve-v1")throw Error("Selected station data is not ready");
    if(next._savedCopy&&data&&!data._savedCopy&&next.checkedAt<=data.checkedAt)return;
    data=next;failed=false;
    if(data.serverTime&&!data._savedCopy)window.WeatherSun?.sync(data.serverTime);
    render();
  }
  async function load(force=false){
    if(busy)return;busy=true;el("refresh-current").disabled=true;
    try{adopt(await window.WeatherPrepared.read(endpoint,{force}));}
    catch(_){failed=true;if(data)render();else{el("current-time").textContent="Current conditions unavailable · try Refresh";}}
    finally{busy=false;el("refresh-current").disabled=false;}
  }
  window.WeatherPrepared.subscribe(endpoint,adopt);
  el("refresh-current").addEventListener("click",()=>load(true));
  el("current-details").addEventListener("toggle",()=>{if(el("current-details").open)renderStations();});
  // These reads retrieve the saved average; only Scheduler contacts MADIS.
  setInterval(()=>{if(!document.hidden&&!el("current").hidden)load();},30000);
  return {select(id){if(id==="current"){render();load();}}};
})();
