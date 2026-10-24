"use strict";
window.WeatherObservations = (() => {
  const el=id=>document.getElementById(id);
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const date=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let data,busy=false;
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const reading=value=>Number.isFinite(value)?`${value.toFixed(1)}°`:"—";
  function wind(value){
    if(!Number.isFinite(value?.speedMph))return "—";
    const speed=Math.round(value.speedMph);
    if(speed===0)return "0";
    const direction=Number.isFinite(value.direction)?["N","NE","E","SE","S","SW","W","NW"][Math.round(value.direction/45)%8]:"?";
    return `${direction} ${speed}`;
  }
  function render(){
    if(!data)return;
    const search=el("observations-search").value.trim().toLowerCase();
    const rows=data.stations.filter(s=>(!search||`${s.station} ${s.displayName} ${s.network}`.toLowerCase().includes(search)));
    el("observations-rows").replaceChildren();
    for(const station of rows){
      const row=node("tr"),site=node("td"),reported=node("td");
      site.className="observation-site";reported.className="observation-reported";
      site.append(node("strong",station.displayName),node("span",station.station,"station-meta"));
      const age=Math.max(0,Math.floor((Date.parse(data.serverTime)-Date.parse(station.time))/60000));
      reported.append(node("time",clock.format(new Date(station.time))),node("span",`${age} min old`,"station-meta"));
      reported.title=date.format(new Date(station.time));
      if(age>30)reported.classList.add("observation-delayed");
      row.append(site,reported);
      for(const [label,value,cls] of [["Temp",reading(station.tempF),"obs-temperature"],["Dewpoint",reading(station.dewpointF),"obs-dewpoint"],["Wind",wind(station.wind),"obs-wind"]]){
        const cell=node("td",value,cls);cell.setAttribute("data-label",label);row.append(cell);
      }
      el("observations-rows").append(row);
    }
    el("observations-empty").hidden=rows.length>0;
    el("observations-empty").textContent=data.stations.length?"No stations match that filter.":"Waiting for the first station collection…";
    el("observations-count").textContent=`${rows.length} / ${data.stations.length} sites`;
    el("observations-checked").textContent=data.checkedAt?`Checked ${clock.format(new Date(data.checkedAt))}`:"";
    const warnings=[];
    if(data.collectorDelayed)warnings.push("Background checks are delayed.");
    if(data.sourceFailures?.length)warnings.push("Some source files could not be refreshed; check each report time.");
    el("observations-status").textContent=warnings.join(" ");el("observations-status").hidden=!warnings.length;
  }
  async function load(){
    if(busy)return;busy=true;el("refresh-observations").disabled=true;
    const started=Date.now();
    try{
      const response=await fetch("/api/observation-stations",{cache:"no-store"});
      const next=await response.json();
      if(!response.ok)throw Error(next.error||"Observations unavailable.");
      data=next;
      if(data.serverTime)window.WeatherSun?.sync(data.serverTime,started);
      render();
    }catch(error){el("observations-status").hidden=false;el("observations-status").textContent=error.message+(data?" Previous readings retained.":"");}
    finally{busy=false;el("refresh-observations").disabled=false;}
  }
  function select(id){if(id==="observations")load();}
  el("refresh-observations").addEventListener("click",load);
  el("observations-search").addEventListener("input",render);
  setInterval(()=>{if(!document.hidden&&!el("observations").hidden)load();},120000);
  return {select};
})();
