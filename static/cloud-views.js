"use strict";
// Routine hourly airport clouds/weather plots; the original COD satellite viewer is independent.
window.WeatherCloudViews = (() => {
  const el = id => document.getElementById(id);
  const time = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const covers = {CLR:"Clear below sensor limit",SKC:"Sky clear",FEW:"Few (1–2 eighths)",SCT:"Scattered (3–4 eighths)",BKN:"Broken (5–7 eighths)",OVC:"Overcast (8 eighths)",VV:"Obscured sky",NSC:"No significant cloud",NCD:"No cloud detected",CAVOK:"CAVOK cloud criteria"};
  let metarMap, markers, cloudData, metarBusy = false, metarIndex = 0;
  const excluded = new Set(["KCFE","KFCE","KSGS"]);
  const preferred = ["KFCM","KMIC","KMSP","KMKT","KRWF","KSTC","KAXN","KDLH","KRST","KBRD","KFAR","KABR","KFSD","KDSM","KLSE","KEAU","KMCW","KMSN","KSTP"];
  const plotScale=.9;
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  const rounded=value=>value==null?"—":String(Math.round(value));
  const windMph=wind=>wind?.speedMph??(wind?.speedKnots==null?null:wind.speedKnots*1.150779);
  const windText=wind=>windMph(wind)==null?"—":windMph(wind)<.5?"Calm":`${wind.direction==null?(wind.variable?"Variable":"?"):directions[Math.round(wind.direction/45)%8]} ${rounded(windMph(wind))} mph`;
  const mode=()=>el("metar-view").value||"plots";
  const timeline=()=>cloudData.history;
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
  function stationModel(station) {
    const wind=station.wind, speed=windMph(wind);
    let arrow;
    if(speed!=null&&speed>=.5&&wind.direction!=null){
      // METAR degrees describe where wind comes FROM; the arrow points TO.
      const toward=(wind.direction+180)%360,path="M0 9V-9M-3 -4L0 -9L3 -4";
      arrow=`<g class="wind-arrow" transform="translate(30 24) rotate(${toward})" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="${path}" stroke="white" stroke-width="4.5"/><path d="${path}" stroke="#111" stroke-width="1.7"/></g>`;
    }else{
      const label=speed==null?"?":speed<.5?"Calm":wind.variable?"VRB":"?";
      arrow=`<text class="plot-wind-state" x="30" y="27" text-anchor="middle">${label}</text>`;
    }
    return `<svg class="metar-plot" width="${84*plotScale}" height="${44*plotScale}" viewBox="0 0 84 44" aria-hidden="true">${arrow}<text class="plot-temp" x="17" y="16" text-anchor="end">${rounded(station.tempF)}</text><text class="plot-dew" x="17" y="37" text-anchor="end">${rounded(station.dewpointF)}</text><text class="plot-speed" x="44" y="29">${rounded(speed)}</text></svg>`;
  }
  function resizeMetarViewer() {
    if(el("metar-clouds").hidden)return;
    const surface=el("metar-cloud-map"),controls=el("metar-viewer-controls");
    const desired=window.innerWidth<600?550:676;
    const available=Math.floor(window.innerHeight-surface.getBoundingClientRect().top-controls.getBoundingClientRect().height-12);
    const height=Math.max(180,Math.min(desired,available));
    if(surface.style.height!==`${height}px`){
      surface.style.height=`${height}px`;
      metarMap?.invalidateSize({pan:false});
    }
  }
  let layoutPending=false;
  function scheduleMetarLayout() {
    if(layoutPending)return;layoutPending=true;
    window.requestAnimationFrame(()=>{layoutPending=false;resizeMetarViewer();});
  }
  window.addEventListener("resize",scheduleMetarLayout);
  window.addEventListener("scroll",scheduleMetarLayout,{passive:true});
  function initMetars() {
    if(metarMap)return;
    resizeMetarViewer();
    metarMap=L.map("metar-cloud-map",{minZoom:5,maxZoom:13,zoomSnap:.25,zoomDelta:.25});
    resetMetarView();
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(metarMap);
    markers=L.layerGroup().addTo(metarMap);
    const density=()=>el("metar-cloud-map").classList.toggle("compact-clouds",metarMap.getZoom()<8);
    metarMap.on("zoomend",density);
    metarMap.on("moveend",renderMetars);density();
  }
  function resetMetarView() {
    // The in-between desktop zoom keeps all three focus airports separated
    // while showing more surroundings than the previous close metro view.
    metarMap?.setView([44.925,-93.35],metarMap.getSize().x<600?9:8.75);
  }
  function inView(station) {
    const p=metarMap.latLngToContainerPoint([station.lat,station.lon]),size=metarMap.getSize();
    return p.x>=0&&p.y>=0&&p.x<=size.x&&p.y<=size.y;
  }
  function plotStations(stations) {
    const candidates=stations.filter(s=>!excluded.has(s.station));
    const priority=s=>{const rank=preferred.indexOf(s.station);return rank<0?preferred.length:rank;};
    candidates.sort((a,b)=>priority(a)-priority(b)||a.station.localeCompare(b.station));
    const size=metarMap.getSize(),accepted=[],boxes=[];
    for(const station of candidates){
      const point=metarMap.latLngToContainerPoint([station.lat,station.lon]);
      if(point.x<0||point.y<0||point.x>size.x||point.y>size.y)continue;
      // Bound the actual labels and short arrow, including white halos and a
      // small gap. Two-digit plots can be closer than long/negative readings.
      const digits=Math.max(rounded(station.tempF).length,rounded(station.dewpointF).length);
      const box={left:point.x+(17-digits*9-30-5)*plotScale,right:point.x+(44+rounded(windMph(station.wind)).length*9-30+5)*plotScale,
        top:point.y-24*plotScale,bottom:point.y+22*plotScale};
      if(boxes.some(b=>box.left<b.right&&box.right>b.left&&box.top<b.bottom&&box.bottom>b.top))continue;
      boxes.push(box);accepted.push(station);
    }
    return accepted;
  }
  function renderMetars() {
    if(!cloudData)return;
    initMetars();markers.clearLayers();
    const hours=timeline();
    metarIndex=Math.max(0,Math.min(metarIndex,hours.length-1));
    const selected=hours[metarIndex],stations=selected.stations.filter(s=>!excluded.has(s.station)),plots=mode()==="plots";
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
    el("metar-cloud-map").setAttribute("aria-label",plots?"Individual station temperature and dew point in Fahrenheit, wind flow arrows and speed in mph":"Cloud ceiling observations");
    el("metar-cloud-legend").hidden=plots;el("metar-plot-legend").hidden=!plots;
    el("metar-table-values").textContent=plots?"Temp / dew (°F) · wind (mph)":"Coverage / bases (ft AGL)";
    const query=el("metar-cloud-search").value.trim().toUpperCase();el("metar-cloud-rows").replaceChildren();
    for(const s of drawn) {
      const layer=ceilingLayer(s);
      const summary=layer?heights(layer,true):"";
      const description=plots?`${rounded(s.tempF)}°F / ${rounded(s.dewpointF)}°F · ${windText(s.wind)}`:layer?(s.hasCeiling?`${layer.cover==="VV"?"Indefinite ceiling":"Ceiling"}: ${heights(layer)}`:`${covers[layer.cover]||layer.cover} · No ceiling reported`):"Cloud information not reported";
      const glyph=plots?stationModel(s):`<span class="cloud-ceiling-number">${summary}</span>`;
      const icon=L.divIcon({className:plots?"weather-station":"cloud-station",html:glyph,iconSize:plots?[84*plotScale,44*plotScale]:[24,24],iconAnchor:plots?[30*plotScale,24*plotScale]:[12,12]});
      const popup=node("div",null,"cloud-popup");popup.append(node("strong",s.station));
      const stamp=plots?(s.weatherTime||s.time):s.time;
      popup.append(node("p",stamp?time.format(new Date(stamp)):"Report time unavailable"));
      if(plots){
        popup.append(node("p",`Temperature ${rounded(s.tempF)}°F · Dew point ${rounded(s.dewpointF)}°F`),node("p",`Wind from ${windText(s.wind)}`));
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
      if(query&&!s.station.includes(query))continue;
      const row=node("tr"),cell=node("td"),button=node("button",s.station,"station-link");
      button.addEventListener("click",()=>{metarMap.setView([s.lat,s.lon],10);el("metar-cloud-map").scrollIntoView({behavior:"smooth",block:"center"});});cell.append(button);
      const stamp=plots?(s.weatherTime||s.time):s.time;
      row.append(cell,node("td",stamp?time.format(new Date(stamp)):"Unavailable"),node("td",plots?`${rounded(s.tempF)} / ${rounded(s.dewpointF)} °F · ${windText(s.wind)}`:s.layers.length?s.layers.map(l=>heights(l)).join(" · "):"Not reported"));
      el("metar-cloud-rows").append(row);
    }
    el("metar-cloud-status").textContent=plots?`${drawn.length} spaced plots visible · ${listing.length} sites in the list · routine hourly snapshot${cloudData.stale?" · Background updates delayed":""}`:`${drawn.length} ceilings visible · ${ceilings.length} broken/overcast ceilings · ${stations.length} reporting stations · routine hourly snapshot${cloudData.stale?" · Background updates delayed":""}${cloudData.historyPending?" · Hourly history is being prepared":""}`;
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
    if(id==="metar-clouds"){scheduledWaitUntil=Date.now()+2*60000;loadMetars();scheduleMetars();scheduleMetarLayout();setTimeout(()=>metarMap?.invalidateSize(),0);}
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
