"use strict";
// Individual routine METAR ceilings, with no full station models or thinning.
window.WeatherCloudViews = (() => {
  const el = id => document.getElementById(id);
  const time = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const covers = {CLR:"Clear below sensor limit",SKC:"Sky clear",FEW:"Few clouds",SCT:"Scattered clouds",BKN:"Broken clouds",OVC:"Overcast",VV:"Obscured sky",NSC:"No significant cloud",NCD:"No cloud detected",CAVOK:"CAVOK cloud criteria"};
  let metarMap, markers, cloudData, metarBusy = false, metarIndex = 0;
  const timeline=()=>cloudData.history;
  const layers=station=>station.cloudLayers||station.layers||[];
  function ceilingLayer(station) {
    const ceilings=layers(station).filter(layer=>["BKN","OVC"].includes(layer.cover));
    // An unknown base could be the lowest layer; do not label a higher one
    // as the lowest ceiling. VV is not a broken/overcast cloud-base report.
    if(ceilings.some(layer=>!Number.isFinite(layer.baseFtAGL)||layer.baseFtAGL<0))return null;
    return ceilings.sort((a,b)=>a.baseFtAGL-b.baseFtAGL)[0]||null;
  }
  function node(tag, text, className) { const n=document.createElement(tag); if(text!=null)n.textContent=text; if(className)n.className=className; return n; }
  async function read(url) { const r=await fetch(url,{cache:"no-store"});const d=await r.json();if(!r.ok)throw Error(d.error||"Data unavailable");return d; }
  function heights(layer) {
    const base=layer.baseFtAGL;
    return `${covers[layer.cover]||layer.cover} · ${base==null?"height unknown":`${base.toLocaleString()} ft ${layer.cover==="VV"?"vertical visibility":"AGL"}`}`;
  }
  function initMetars() {
    if(metarMap)return;
    metarMap=L.map("metar-cloud-map",{minZoom:5,maxZoom:13,zoomSnap:.1,zoomDelta:.1});
    resetMetarView();
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(metarMap);
    markers=L.layerGroup().addTo(metarMap);
    metarMap.on("moveend",renderMetars);
  }
  function resetMetarView() {
    metarMap?.setView([44.925,-93.35],metarMap.getSize().x<600?9:8.5);
  }
  function inView(station) {
    const p=metarMap.latLngToContainerPoint([station.lat,station.lon]),size=metarMap.getSize();
    return p.x>=0&&p.y>=0&&p.x<=size.x&&p.y<=size.y;
  }
  function renderMetars() {
    if(!cloudData)return;
    initMetars();markers.clearLayers();
    const hours=timeline();
    metarIndex=Math.max(0,Math.min(metarIndex,hours.length-1));
    // Use actual airport rows, including KFCM/KMIC/KMSP separately. The
    // synthetic metro average is reserved for the independent Current tab.
    const selected=hours[metarIndex],stations=selected.stations;
    const ceilings=stations.filter(ceilingLayer),drawn=ceilings.filter(inView);
    const slider=el("metar-cloud-timeline");
    slider.max=String(hours.length-1);slider.value=String(metarIndex);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*metarIndex/(hours.length-1):0}%`);
    el("metar-cloud-time").textContent=`${time.format(new Date(selected.hour))} · hourly ${metarIndex+1}/${hours.length}`;
    slider.setAttribute("aria-valuetext",el("metar-cloud-time").textContent);
    const query=el("metar-cloud-search").value.trim().toUpperCase();el("metar-cloud-rows").replaceChildren();
    // Every qualifying airport in view gets a number; there is no collision
    // suppression, station priority list, or limit on marker count.
    for(const station of drawn) {
      const layer=ceilingLayer(station),number=String(Math.round(layer.baseFtAGL/100));
      const icon=L.divIcon({className:"cloud-station",html:`<span class="cloud-ceiling-number">${number}</span>`,iconSize:[40,24],iconAnchor:[20,12]});
      const popup=node("div",null,"cloud-popup");popup.append(node("strong",station.station));
      popup.append(node("p",station.time?time.format(new Date(station.time)):"Report time unavailable"));
      popup.append(node("p",`Lowest broken/overcast base: ${layer.baseFtAGL.toLocaleString()} ft AGL`));
      for(const cloud of layers(station))popup.append(node("p",heights(cloud)));
      L.marker([station.lat,station.lon],{icon,title:`${station.station} · ${heights(layer)}`,keyboard:true}).bindPopup(popup).addTo(markers);
    }
    // Keep every reporting site searchable, including sites with nothing
    // drawn. Cloud-only values remain in the table; no temperature/wind plots.
    if(el("metar-station-list").open)for(const station of stations){
      if(query&&!station.station.includes(query))continue;
      const row=node("tr"),cell=node("td"),button=node("button",station.station,"station-link");
      button.addEventListener("click",()=>{metarMap.setView([station.lat,station.lon],10);el("metar-cloud-map").scrollIntoView({behavior:"smooth",block:"center"});});cell.append(button);
      const layer=ceilingLayer(station);
      row.append(cell,node("td",station.time?time.format(new Date(station.time)):"Unavailable"),node("td",layer?heights(layer):"No known broken/overcast base · not plotted"));
      el("metar-cloud-rows").append(row);
    }
    el("metar-cloud-status").textContent=`${drawn.length} ceiling heights visible · ${ceilings.length} known broken/overcast ceilings · ${stations.length} airport reports · ${hours.filter(hour=>hour.stations.length).length}/12 hours with reports · :45–:59 METARs · updates at :00${cloudData.stale?" · Background updates delayed":""}${cloudData.historyPending?" · Hourly history is being prepared":""}`;
  }
  let metarRetry, scheduledWaitUntil=0;
  function retryPreparedMetars() {
    clearTimeout(metarRetry);
    if(scheduledWaitUntil>Date.now())metarRetry=setTimeout(()=>{
      if(!document.hidden&&!el("metar-clouds").hidden)loadMetars();
    },60000);
  }
  async function loadMetars() {
    if(metarBusy)return;metarBusy=true;el("refresh-metar-clouds").disabled=true;
    try {
      const data=await read("/api/metar-clouds");
      const selected=cloudData?.history[metarIndex]?.hour;
      const followLatest=!cloudData||metarIndex===timeline().length-1;
      cloudData=data;
      const restored=!followLatest&&selected?data.history.findIndex(h=>h.hour===selected):-1;
      metarIndex=restored>=0?restored:followLatest?timeline().length-1:0;
      renderMetars();
      // After the :00 collection starts, wait for its prepared result rather
      // than treating the old snapshot as this hour's completed update. These
      // bounded reads never trigger additional upstream collection.
      const now=new Date(),due=new Date(now);due.setUTCMinutes(0,0,0);
      if(due>now)due.setUTCHours(due.getUTCHours()-1);
      clearTimeout(metarRetry);
      if(scheduledWaitUntil>Date.now()&&new Date(data.checkedAt)<due){
        retryPreparedMetars();
      }else scheduledWaitUntil=0;
    }
    catch(e){el("metar-cloud-status").textContent=`${e.message}${cloudData?" Previous reports retained; check their timestamps.":""}`;retryPreparedMetars();}
    finally{metarBusy=false;el("refresh-metar-clouds").disabled=false;}
  }

  let metarTimer;
  function scheduleMetars() {
    clearTimeout(metarTimer);
    const now=new Date(),hour=new Date(now);hour.setUTCMinutes(0,0,0);
    const next=[0,1].map(offset=>new Date(hour.getTime()+offset*3600000+30000)).find(t=>t>now);
    metarTimer=setTimeout(()=>{
      if(!document.hidden&&!el("metar-clouds").hidden){scheduledWaitUntil=Date.now()+2*60000;loadMetars();}
      scheduleMetars();
    },next-now);
  }
  function select(id) {
    if(id==="metar-clouds"){scheduledWaitUntil=Date.now()+2*60000;loadMetars();scheduleMetars();setTimeout(()=>metarMap?.invalidateSize(),0);}
  }
  el("refresh-metar-clouds").addEventListener("click",loadMetars);
  el("metar-cloud-search").addEventListener("input",renderMetars);
  el("metar-station-list").addEventListener("toggle",()=>{if(el("metar-station-list").open)renderMetars();});
  el("metar-cloud-reset").addEventListener("click",resetMetarView);
  el("metar-cloud-timeline").addEventListener("input",event=>{metarIndex=Number(event.target.value);renderMetars();});
  window.WeatherFullscreen.attach({surfaceId:"metar-surface",buttonId:"metar-fullscreen",label:"METAR map",onResize:()=>{if(metarMap){metarMap.invalidateSize({pan:false});renderMetars();}}});
  scheduleMetars();
  return {select};
})();

