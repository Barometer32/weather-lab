"use strict";
// Original compact hourly airport station models; all source reads stay in the collector.
window.WeatherCloudViews = (() => {
  const el = id => document.getElementById(id);
  const time = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let metarMap, markers, cloudData, metarBusy = false, metarIndex = 0, followLatest = true;
  const timeline=()=>cloudData.history;
  const model=window.WeatherStationModel;
  const rounded=value=>value==null?"—":String(Math.round(value));
  const windMph=wind=>wind?.speedMph??(wind?.speedKnots==null?null:wind.speedKnots*1.150779);
  function windText(wind) {
    const speed=windMph(wind);
    if(speed==null)return "—";
    if(speed<.5)return "0 mph";
    const direction=wind.direction==null?(wind.variable?"VRB":"?"):["N","NE","E","SE","S","SW","W","NW"][Math.round(wind.direction/45)%8];
    return `${direction} ${rounded(speed)} mph`;
  }
  function node(tag, text, className) { const n=document.createElement(tag); if(text!=null)n.textContent=text; if(className)n.className=className; return n; }
  async function read(url) { const r=await fetch(url,{cache:"no-store"});const d=await r.json();if(!r.ok)throw Error(d.error||"Data unavailable");return d; }
  function initMetars() {
    if(metarMap)return;
    metarMap=L.map("metar-cloud-map",{minZoom:5,maxZoom:13,zoomSnap:.25,zoomDelta:.25,wheelPxPerZoomLevel:90});
    resetMetarView();
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(metarMap);
    markers=L.layerGroup().addTo(metarMap);
    metarMap.on("moveend",renderMetars);
  }
  function resetMetarView() {
    metarMap?.setView([44.925,-93.35],metarMap.getSize().x<600?9:8.5);
  }
  function plotStations(stations) {
    // Reserve each model's largest footprint over the loop, so changing
    // digits never change neighboring station visibility.
    const sites=new Map(),gap=2;
    for(const hour of timeline())for(const station of hour.stations){
      const footprint=model.footprint(station),old=sites.get(station.station);
      sites.set(station.station,{station,footprint:old?{
        left:Math.min(old.footprint.left,footprint.left),right:Math.max(old.footprint.right,footprint.right),
        top:Math.min(old.footprint.top,footprint.top),bottom:Math.max(old.footprint.bottom,footprint.bottom)
      }:footprint});
    }
    const preferred=["KFCM","KMIC","KMSP","KSTP","KMKT","KRWF","KSTC","KAXN","KDLH","KRST","KBRD","KFAR","KABR","KFSD","KDSM","KLSE","KEAU","KMCW","KMSN"];
    const priority=station=>{const rank=preferred.indexOf(station.station);return rank<0?preferred.length:rank;};
    const candidates=[...sites.values()].sort((a,b)=>priority(a.station)-priority(b.station)||a.station.station.localeCompare(b.station.station));
    const size=metarMap.getSize(),boxes=[],accepted=new Set();
    const point=station=>metarMap.latLngToContainerPoint([station.lat,station.lon]);
    const inView=station=>{const p=point(station);return p.x>=0&&p.y>=0&&p.x<=size.x&&p.y<=size.y;};
    for(const {station,footprint:f} of candidates){
      if(!inView(station))continue;
      const p=point(station),box={left:p.x+f.left,right:p.x+f.right,top:p.y+f.top,bottom:p.y+f.bottom};
      if(boxes.some(b=>box.left<b.right+gap&&box.right>b.left-gap&&box.top<b.bottom+gap&&box.bottom>b.top-gap))continue;
      boxes.push(box);accepted.add(station.station);
    }
    return {drawn:stations.filter(station=>accepted.has(station.station)),inView:stations.filter(inView).length};
  }
  function renderMetars() {
    if(!cloudData)return;
    initMetars();markers.clearLayers();
    const hours=timeline();
    if(followLatest){
      const available=hours.findLastIndex(hour=>hour.stations.length>0);
      metarIndex=available>=0?available:hours.length-1;
    }
    metarIndex=Math.max(0,Math.min(metarIndex,hours.length-1));
    // Every airport stays at its own coordinates in every hourly frame.
    const selected=hours[metarIndex],stations=selected.stations;
    const {drawn,inView}=plotStations(stations);
    const slider=el("metar-cloud-timeline");
    slider.max=String(hours.length-1);slider.value=String(metarIndex);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*metarIndex/(hours.length-1):0}%`);
    el("metar-cloud-time").textContent=`${time.format(new Date(selected.hour))} · hourly ${metarIndex+1}/${hours.length}`;
    slider.setAttribute("aria-valuetext",el("metar-cloud-time").textContent);
    const query=el("metar-cloud-search").value.trim().toUpperCase();el("metar-cloud-rows").replaceChildren();
    for(const station of drawn) {
      const icon=L.divIcon({className:"weather-station",html:model.stationModel(station),iconSize:model.iconSize,iconAnchor:model.iconAnchor});
      const popup=node("div",null,"cloud-popup");popup.append(node("strong",station.station));
      popup.append(node("p",`${station.network||"Airport METAR"} · ${station.source||"NOAA Aviation Weather Center"}`));
      popup.append(node("p",station.time?time.format(new Date(station.time)):"Report time unavailable"));
      popup.append(node("p",`Temperature ${rounded(station.tempF)}°F · Dewpoint ${rounded(station.dewpointF)}°F`));
      popup.append(node("p",`Wind ${windText(station.wind)}`));
      L.marker([station.lat,station.lon],{icon,title:`${station.station} · ${rounded(station.tempF)}°F / ${rounded(station.dewpointF)}°F · ${windText(station.wind)}`,keyboard:true}).bindPopup(popup).addTo(markers);
    }
    // The searchable list includes every eligible report in the regional frame.
    if(el("metar-station-list").open)for(const station of stations){
      if(query&&!`${station.station} ${station.name||""} ${station.network||""}`.toUpperCase().includes(query))continue;
      const row=node("tr"),cell=node("td"),button=node("button",station.station,"station-link");
      button.addEventListener("click",()=>{metarMap.setView([station.lat,station.lon],10);el("metar-cloud-map").scrollIntoView({behavior:"smooth",block:"center"});});cell.append(button);
      row.append(cell,node("td",station.time?time.format(new Date(station.time)):"Unavailable"),node("td",`${station.network||"Airport METAR"} · ${rounded(station.tempF)} / ${rounded(station.dewpointF)} °F · ${windText(station.wind)}`));
      el("metar-cloud-rows").append(row);
    }
    el("metar-cloud-status").textContent=`${drawn.length} airport plots in view${inView>drawn.length?` · ${inView-drawn.length} nearby plots hidden for spacing; zoom in`:""} · ${stations.length} airport METARs in this hour · ${hours.filter(hour=>hour.stations.length).length}/12 hours with reports · routine reports :45–:59 · :00 collection with two-minute retries${!hours.at(-1).stations.length?` · Waiting for ${time.format(new Date(hours.at(-1).hour))} reports${stations.length?"; showing the latest available hour":""}`:""}${cloudData.stale?" · Background updates delayed":""}${cloudData.historyPending?" · Hourly history is being prepared":""}`;
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
      const data=await read("/api/station-plots");
      const selected=cloudData?.history[metarIndex]?.hour;
      cloudData=data;
      if(data.serverTime)window.WeatherSun?.sync(data.serverTime);
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
  // Poll prepared objects only; NOAA downloads are performed by the scheduler.
  setInterval(()=>{if(!document.hidden&&!el("metar-clouds").hidden)loadMetars();},60000);
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
  el("metar-cloud-timeline").addEventListener("input",event=>{metarIndex=Number(event.target.value);followLatest=metarIndex===timeline().length-1;renderMetars();});
  window.WeatherFullscreen.attach({surfaceId:"metar-surface",buttonId:"metar-fullscreen",label:"METAR map",onResize:()=>{if(metarMap){metarMap.invalidateSize({pan:false});renderMetars();}}});
  scheduleMetars();
  return {select};
})();

