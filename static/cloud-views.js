"use strict";
// Fresh Mesonet station plots and routine hourly airport cloud ceilings.
window.WeatherCloudViews = (() => {
  const el = id => document.getElementById(id);
  const time = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const covers = {CLR:"Clear below sensor limit",SKC:"Sky clear",FEW:"Few (1–2 eighths)",SCT:"Scattered (3–4 eighths)",BKN:"Broken (5–7 eighths)",OVC:"Overcast (8 eighths)",VV:"Obscured sky",NSC:"No significant cloud",NCD:"No cloud detected",CAVOK:"CAVOK cloud criteria"};
  let metarMap, markers, metarBusy = false;
  const datasets={}, indices={plots:0,clouds:0};
  const excluded = new Set(["KCFE","KFCE","KSGS"]);
  const preferred = ["KFCM","KMIC","KMSP","KMKT","KRWF","KSTC","KAXN","KDLH","KRST","KBRD","KFAR","KABR","KFSD","KDSM","KLSE","KEAU","KMCW","KMSN","KSTP"];
  const plotScale=.82;
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  const rounded=value=>value==null?"—":String(Math.round(value));
  const windMph=wind=>wind?.speedMph??(wind?.speedKnots==null?null:wind.speedKnots*1.150779);
  const windText=wind=>windMph(wind)==null?"—":windMph(wind)<.5?"Calm":`${wind.direction==null?(wind.variable?"Variable":"?"):directions[Math.round(wind.direction/45)%8]} ${rounded(windMph(wind))} mph`;
  const mode=()=>el("metar-view").value||"plots";
  const dataset=()=>datasets[mode()];
  const timeline=()=>{const d=dataset();return mode()==="plots"&&d.maxAgeMinutes!=null?d.history.concat([{hour:d.checkedAt,isLive:true,stations:d.stations}]):d.history;};
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
    // The in-between desktop zoom keeps all three focus airports separated
    // while showing more surroundings than the previous close metro view.
    metarMap?.setView([44.925,-93.35],metarMap.getSize().x<600?9:8.5);
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
    const cloudData=dataset();if(!cloudData)return;
    initMetars();markers.clearLayers();
    const hours=timeline();
    let metarIndex=Math.max(0,Math.min(indices[mode()],hours.length-1));indices[mode()]=metarIndex;
    const selected=hours[metarIndex],stations=selected.stations.filter(s=>!excluded.has(s.station)),plots=mode()==="plots";
    const ceilings=plots?[]:stations.filter(ceilingLayer);
    const drawn=plots?plotStations(stations):ceilings.filter(inView);
    const slider=el("metar-cloud-timeline");
    slider.max=String(hours.length-1);slider.value=String(metarIndex);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*metarIndex/(hours.length-1):0}%`);
    el("metar-cloud-time").textContent=selected.isLive?`Latest reports · checked ${time.format(new Date(cloudData.checkedAt))}`:`${time.format(new Date(selected.hour))} · hourly ${metarIndex+1}/${cloudData.history.length}`;
    slider.setAttribute("aria-valuetext",el("metar-cloud-time").textContent);
    el("metar-heading").textContent=plots?"Station plots":"Cloud ceilings";
    el("metar-timeline-description").textContent=plots?"Latest station reports + 12 hourly snapshots · zoom in for more":"Last 12 routine hourly airport snapshots";
    slider.setAttribute("aria-label",plots?"Station timeline: twelve hourly snapshots and latest reports":"METAR cloud timeline: twelve routine hourly snapshots");
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
      if(s.name&&s.name!==s.station)popup.append(node("p",s.name));
      if(s.network)popup.append(node("p",`Network: ${s.network} · Source: ${s.source||"Iowa Environmental Mesonet"}`));
      const stamp=plots?(s.weatherTime||s.time):s.time;
      popup.append(node("p",stamp?time.format(new Date(stamp)):"Report time unavailable"));
      if(plots){
        popup.append(node("p",`Temperature ${s.tempF==null?"—":s.tempF.toFixed(1)}°F · Dew point ${s.dewpointF==null?"—":s.dewpointF.toFixed(1)}°F`),node("p",`Wind from ${windText(s.wind)}`));
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
      if(query&&!`${s.station} ${s.name||""} ${s.network||""}`.toUpperCase().includes(query))continue;
      const row=node("tr"),cell=node("td"),button=node("button",s.network?`${s.station} · ${s.network}`:s.station,"station-link");
      button.addEventListener("click",()=>{metarMap.setView([s.lat,s.lon],10);el("metar-cloud-map").scrollIntoView({behavior:"smooth",block:"center"});});cell.append(button);
      const stamp=plots?(s.weatherTime||s.time):s.time;
      row.append(cell,node("td",stamp?time.format(new Date(stamp)):"Unavailable"),node("td",plots?`${rounded(s.tempF)} / ${rounded(s.dewpointF)} °F · ${windText(s.wind)}`:s.layers.length?s.layers.map(l=>heights(l)).join(" · "):"Not reported"));
      el("metar-cloud-rows").append(row);
    }
    const missing=cloudData.failedStates?.length?` · Some feeds delayed: ${cloudData.failedStates.join(", ")}`:"";
    el("metar-cloud-status").textContent=plots?`${drawn.length} spaced plots visible · ${listing.length} reporting sites · ${selected.isLive?"Latest reports (up to 90 minutes old)":"Hourly station snapshot"}${cloudData.stale?" · Background updates delayed":""}${missing}${listing.length?"":" · No reports available for this time"}`:`${drawn.length} ceilings visible · ${ceilings.length} broken/overcast ceilings · ${stations.length} reporting airports · routine hourly snapshot${cloudData.stale?" · Background updates delayed":""}${cloudData.historyPending?" · Hourly history is being prepared":""}${stations.length?"":" · No airport reports available for this hour"}`;
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
    const view=mode();
    try {
      const previous=datasets[view], index=indices[view];
      const previousHours=previous?(view==="plots"&&previous.maxAgeMinutes!=null?previous.history.concat([{hour:previous.checkedAt,isLive:true,stations:previous.stations}]):previous.history):[];
      const selected=previousHours[index]?.hour;
      const followLatest=!previous||index===previousHours.length-1;
      const data=await read(view==="plots"?"/api/station-plots":"/api/metar-clouds");
      datasets[view]=data;
      const hours=view==="plots"&&data.maxAgeMinutes!=null?data.history.concat([{hour:data.checkedAt,isLive:true,stations:data.stations}]):data.history;
      const restored=!followLatest&&selected?hours.findIndex(h=>h.hour===selected):-1;
      indices[view]=restored>=0?restored:followLatest?hours.length-1:0;
      if(mode()===view)renderMetars();
      // Bounded reads wait for scheduled prepared data; visitors never launch
      // upstream station downloads or the private collectors.
      const now=new Date(),due=new Date(now);due.setUTCMinutes(view==="plots"?Math.floor(now.getUTCMinutes()/5)*5:0,0,0);
      clearTimeout(metarRetry);
      if(mode()===view&&scheduledWaitUntil>Date.now()&&new Date(data.checkedAt)<due){retryPreparedMetars();}
      else scheduledWaitUntil=0;
    }
    catch(e){if(mode()===view)el("metar-cloud-status").textContent=`${e.message}${datasets[view]?" Previous reports retained; check their timestamps.":""}`;retryPreparedMetars();}
    finally{metarBusy=false;el("refresh-metar-clouds").disabled=false;if(mode()!==view)loadMetars();}
  }

  let metarTimer;
  function scheduleMetars() {
    clearTimeout(metarTimer);
    const now=new Date(),interval=mode()==="plots"?300000:3600000;
    const next=(Math.floor((now.getTime()-30000)/interval)+1)*interval+30000;
    metarTimer=setTimeout(()=>{
      if(!document.hidden&&!el("metar-clouds").hidden){scheduledWaitUntil=Date.now()+2*60000;loadMetars();}
      scheduleMetars();
    },next-now);
  }
  function select(id) {
    if(id==="metar-clouds"){initMetars();scheduledWaitUntil=Date.now()+2*60000;loadMetars();scheduleMetars();setTimeout(()=>metarMap?.invalidateSize(),0);}
  }
  el("refresh-metar-clouds").addEventListener("click",loadMetars);
  el("metar-cloud-search").addEventListener("input",renderMetars);
  el("metar-station-list").addEventListener("toggle",()=>{if(el("metar-station-list").open)renderMetars();});
  el("metar-cloud-reset").addEventListener("click",resetMetarView);
  el("metar-cloud-timeline").addEventListener("input",event=>{indices[mode()]=Number(event.target.value);renderMetars();});
  el("metar-view").addEventListener("change",()=>{
    markers?.clearLayers();scheduleMetars();
    if(dataset())renderMetars();else el("metar-cloud-status").textContent="Loading station reports…";
    loadMetars();
  });
  scheduleMetars();
  return {select};
})();
