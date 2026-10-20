"use strict";
// Routine hourly airport clouds/weather plots; the original COD satellite viewer is independent.
window.WeatherCloudViews = (() => {
  const el = id => document.getElementById(id);
  const time = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const covers = {CLR:"Clear below sensor limit",SKC:"Sky clear",FEW:"Few (1–2 eighths)",SCT:"Scattered (3–4 eighths)",BKN:"Broken (5–7 eighths)",OVC:"Overcast (8 eighths)",VV:"Obscured sky",NSC:"No significant cloud",NCD:"No cloud detected",CAVOK:"CAVOK cloud criteria"};
  let metarMap, markers, cloudData, metarBusy = false, metarIndex = 0;
  const excluded = new Set(["KCFE","KFCE","KSGS"]);
  const metroSites = new Set(["KFCM","KMIC","KMSP"]);
  const preferred = ["METRO","KMKT","KRWF","KSTC","KAXN","KDLH","KRST","KBRD","KFAR","KABR","KFSD","KDSM","KLSE","KEAU","KMCW","KMSN","KSTP"];
  const model=window.WeatherStationModel;
  const plotScale=model.scale;
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  const rounded=value=>value==null?"—":String(Math.round(value));
  const windMph=wind=>wind?.speedMph??(wind?.speedKnots==null?null:wind.speedKnots*1.150779);
  const windText=wind=>windMph(wind)==null?"—":windMph(wind)<.5?"Calm":`${wind.direction==null?(wind.variable?"Variable":"?"):directions[Math.round(wind.direction/45)%8]} ${rounded(windMph(wind))} mph`;
  const mode=()=>el("metar-view").value||"plots";
  const timeline=()=>cloudData.history;
  const displayStations=frame=>frame.metro
    ? [...frame.stations.filter(s=>!excluded.has(s.station)&&!metroSites.has(s.station)),frame.metro]
    : frame.stations.filter(s=>!excluded.has(s.station));
  const stationName=s=>s.isMetro?"Metro average · KFCM + KMIC + KMSP":s.station;
  const ceilingLayer=s=>(s.layers||[]).filter(l=>["BKN","OVC"].includes(l.cover)&&l.baseFtAGL!=null).sort((a,b)=>a.baseFtAGL-b.baseFtAGL)[0];
  function node(tag, text, className) { const n=document.createElement(tag); if(text!=null)n.textContent=text; if(className)n.className=className; return n; }
  async function read(url) { const r=await fetch(url,{cache:"no-store"});const d=await r.json();if(!r.ok)throw Error(d.error||"Data unavailable");return d; }
  function heights(layer, compact=false) {
    if(layer.cover==="CLR")return compact?"":"CLR · no clouds detected ≤12,000 ft";
    if(["SKC","NSC","NCD","CAVOK"].includes(layer.cover))return compact?"":`${layer.cover} · ${covers[layer.cover]}`;
    const h=layer.baseFtAGL;
    const base=h==null?(compact?"?":"height unknown"):compact?String(Math.max(1,Math.round(h/1000))):`${h.toLocaleString()} ft`;
    if(compact)return `${layer.cover==="VV"?"VV ":""}${base}`;
    return `${covers[layer.cover]||layer.cover} · ${base}${layer.cover==="VV"?" vertical visibility":""}`;
  }
  const stationModel=station=>model.stationModel(station);
  function initMetars() {
    if(metarMap)return;
    metarMap=L.map("metar-cloud-map",{minZoom:5,maxZoom:13,zoomSnap:.1,zoomDelta:.1});
    resetMetarView();
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(metarMap);
    markers=L.layerGroup().addTo(metarMap);
    const density=()=>el("metar-cloud-map").classList.toggle("compact-clouds",metarMap.getZoom()<8);
    metarMap.on("zoomend",density);
    metarMap.on("moveend",renderMetars);density();
  }
  function resetMetarView() {
    // Keep the existing metro extent and fractional zoom control.
    metarMap?.setView([44.925,-93.35],metarMap.getSize().x<600?9:8.5);
  }
  function inView(station) {
    const p=metarMap.latLngToContainerPoint([station.lat,station.lon]),size=metarMap.getSize();
    return p.x>=0&&p.y>=0&&p.x<=size.x&&p.y<=size.y;
  }
  function plotStations(stations) {
    // Reserve each station's largest footprint across the complete timeline.
    // Missing reports keep their space; nearby plots cannot take turns using
    // that slot as the slider moves. This never carries a report forward.
    const reserved=new Map();
    for(const hour of timeline())for(const s of displayStations(hour)){
      if(excluded.has(s.station))continue;
      const f=model.footprint(s),old=reserved.get(s.station);
      reserved.set(s.station,{station:s.station,lat:s.lat,lon:s.lon,footprint:old?{
        left:Math.min(old.footprint.left,f.left),right:Math.max(old.footprint.right,f.right),
        top:Math.min(old.footprint.top,f.top),bottom:Math.max(old.footprint.bottom,f.bottom)
      }:f});
    }
    const candidates=[...reserved.values()];
    const priority=s=>{const rank=preferred.indexOf(s.station);return rank<0?preferred.length:rank;};
    candidates.sort((a,b)=>priority(a)-priority(b)||a.station.localeCompare(b.station));
    const size=metarMap.getSize(),accepted=[],boxes=[];
    for(const station of candidates){
      const point=metarMap.latLngToContainerPoint([station.lat,station.lon]);
      if(point.x<0||point.y<0||point.x>size.x||point.y>size.y)continue;
      // Use the same reserved box for every hour at this map view.
      const f=station.footprint;
      const box={left:point.x+f.left,right:point.x+f.right,top:point.y+f.top,bottom:point.y+f.bottom};
      if(boxes.some(b=>box.left<b.right&&box.right>b.left&&box.top<b.bottom&&box.bottom>b.top))continue;
      boxes.push(box);accepted.push(station);
    }
    const selected=new Map(stations.map(s=>[s.station,s]));
    return accepted.map(s=>selected.get(s.station)).filter(Boolean);
  }
  function renderMetars() {
    if(!cloudData)return;
    initMetars();markers.clearLayers();
    const hours=timeline();
    metarIndex=Math.max(0,Math.min(metarIndex,hours.length-1));
    const selected=hours[metarIndex],stations=displayStations(selected),plots=mode()==="plots";
    const ceilings=plots?[]:stations.filter(ceilingLayer);
    const drawn=plots?plotStations(stations):ceilings.filter(inView);
    const slider=el("metar-cloud-timeline");
    slider.max=String(hours.length-1);slider.value=String(metarIndex);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*metarIndex/(hours.length-1):0}%`);
    el("metar-cloud-time").textContent=`${time.format(new Date(selected.hour))} · hourly ${metarIndex+1}/${cloudData.history.length}`;
    slider.setAttribute("aria-valuetext",el("metar-cloud-time").textContent);
    el("metar-heading").textContent=plots?"METAR plots":"Cloud ceilings";
    el("metar-timeline-description").textContent="Last 12 routine hourly snapshots";
    slider.setAttribute("aria-label","Manual METAR timeline: last 12 routine hourly snapshots");
    el("metar-cloud-map").setAttribute("aria-label",plots?"Station temperature and dew point, cloud-cover circle, ceiling in hundreds of feet, and wind flow arrow and speed":"Cloud ceiling observations");
    el("metar-cloud-legend").hidden=plots;el("metar-plot-legend").hidden=!plots;
    el("metar-table-values").textContent=plots?"Temp / dew (°F) · wind (mph)":"Coverage / bases (ft AGL)";
    const query=el("metar-cloud-search").value.trim().toUpperCase();el("metar-cloud-rows").replaceChildren();
    for(const s of drawn) {
      const layer=ceilingLayer(s);
      const summary=layer?heights(layer,true):"";
      const description=plots?`${rounded(s.tempF)}°F / ${rounded(s.dewpointF)}°F · ${windText(s.wind)}`:layer?(s.hasCeiling?`${layer.cover==="VV"?"Indefinite ceiling":"Ceiling"}: ${heights(layer)}`:`${covers[layer.cover]||layer.cover} · No ceiling reported`):"Cloud information not reported";
      const glyph=plots?stationModel(s):`<span class="cloud-ceiling-number">${summary}</span>`;
      const icon=L.divIcon({className:plots?"weather-station":"cloud-station",html:glyph,iconSize:plots?model.iconSize:[24,24],iconAnchor:plots?model.iconAnchor:[12,12]});
      const popup=node("div",null,"cloud-popup");popup.append(node("strong",stationName(s)));
      if(s.isMetro){
        popup.append(node("p",s.available?"Temperature, dew point and wind: equal three-airport averages; wind direction is speed-weighted circular.":`Metro average unavailable: ${s.qa?.stationsUsed??0}/3 stations passed temperature, dew point and wind checks. No older reports substituted.`));
        if(s.cloudSource)popup.append(node("p",`Cloud cover and ceiling: ${s.cloudSource} report (not averaged).`));
        for(const contributor of s.contributors||[]){
          popup.append(node("p",`${contributor.code}: ${contributor.observedAt?time.format(new Date(contributor.observedAt)):"routine report missing"}`));
        }
      }
      const stamp=plots?(s.weatherTime||s.time):s.time;
      popup.append(node("p",stamp?time.format(new Date(stamp)):"Report time unavailable"));
      if(plots){
        popup.append(node("p",`Temperature ${rounded(s.tempF)}°F · Dew point ${rounded(s.dewpointF)}°F`),node("p",`Wind from ${windText(s.wind)}`),node("p",model.cloudText(s)));
      }else{
        if(layer)popup.append(node("p",description));
        if(!s.layers.length)popup.append(node("p","Cloud information not reported."));
        for(const cloud of s.layers)popup.append(node("p",`${heights(cloud)}${cloud.baseFtAGL!=null&&cloud.cover!=="VV"?" AGL":""}`));
      }
      L.marker([s.lat,s.lon],{icon,title:`${s.station} · ${description}`,keyboard:true}).bindPopup(popup).addTo(markers);
    }
    const listing=plots?stations:ceilings;
    // Off-screen sites remain searchable without constructing a
    // regional table every time the map moves. Populate it only when opened.
    if(el("metar-station-list").open)for(const s of listing){
      if(query&&!stationName(s).toUpperCase().includes(query)&&!s.station.includes(query))continue;
      const row=node("tr"),cell=node("td"),button=node("button",s.isMetro?"Metro average (KFCM + KMIC + KMSP)":s.station,"station-link");
      button.addEventListener("click",()=>{metarMap.setView([s.lat,s.lon],10);el("metar-cloud-map").scrollIntoView({behavior:"smooth",block:"center"});});cell.append(button);
      const stamp=plots?(s.weatherTime||s.time):s.time;
      row.append(cell,node("td",stamp?time.format(new Date(stamp)):"Unavailable"),node("td",plots?`${rounded(s.tempF)} / ${rounded(s.dewpointF)} °F · ${windText(s.wind)} · ${model.cloudText(s)}`:s.layers.length?s.layers.map(l=>heights(l)).join(" · "):"Not reported"));
      el("metar-cloud-rows").append(row);
    }
    el("metar-cloud-status").textContent=plots?`${drawn.length} spaced plots visible · ${listing.length} sites in the list · ${hours.filter(h=>h.stations.length).length}/12 hours with reports · :45–:59 METARs · updates at :02${cloudData.stale?" · Background updates delayed":""}`:`${drawn.length} ceilings visible · ${ceilings.length} broken/overcast ceilings · ${stations.length} reporting stations · routine hourly snapshot${cloudData.stale?" · Background updates delayed":""}${cloudData.historyPending?" · Hourly history is being prepared":""}`;
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
      // After the :02 collection starts, wait for its prepared result rather
      // than treating the old snapshot as this hour's completed update. These
      // bounded reads never trigger additional upstream collection.
      const now=new Date(),due=new Date(now);due.setUTCMinutes(2,0,0);
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
    const next=[0,1].map(offset=>new Date(hour.getTime()+offset*3600000+150000)).find(t=>t>now);
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
  el("metar-view").addEventListener("change",renderMetars);
  scheduleMetars();
  return {select};
})();

