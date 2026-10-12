"use strict";
// Live and hourly airport clouds/weather plots; the original COD satellite viewer is independent.
window.WeatherCloudViews = (() => {
  const el = id => document.getElementById(id);
  const time = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const covers = {CLR:"Clear below sensor limit",SKC:"Sky clear",FEW:"Few (1–2 eighths)",SCT:"Scattered (3–4 eighths)",BKN:"Broken (5–7 eighths)",OVC:"Overcast (8 eighths)",VV:"Obscured sky",NSC:"No significant cloud",NCD:"No cloud detected",CAVOK:"CAVOK cloud criteria"};
  let metarMap, markers, cloudData, metarBusy = false, metarIndex = 0;
  const metroSites = new Set(["KFCM","KMSP","KMIC"]);
  const preferred = ["METRO","KMKT","KRWF","KSTC","KAXN","KDLH","KRST","KBRD","KFAR","KABR","KFSD","KDSM","KLSE","KEAU","KMCW","KMSN"];
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  const rounded=value=>value==null?"—":String(Math.round(value));
  const windText=wind=>wind?.speedKnots==null?"—":wind.speedKnots<.5?"Calm":`${wind.direction==null?(wind.variable?"VRB":"?"):directions[Math.round(wind.direction/45)%8]} ${rounded(wind.speedKnots)} kt`;
  const mode=()=>el("metar-view").value||"clouds";
  const timeline=()=>mode()==="plots"?cloudData.history:[...cloudData.history,cloudData.live];
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
    const wind=station.wind, speed=wind?.speedKnots;
    let staff="";
    if(speed!=null&&speed<.5){
      staff='<circle class="calm-ring" cx="0" cy="0" r="11" fill="none"/>';
    }else if(speed!=null&&wind.direction!=null){
      let knots=Math.round(speed/5)*5, y=-35;
      staff='<path class="wind-staff" d="M0 0V-35"/>';
      while(knots>=50){
        staff+=`<path class="wind-pennant" d="M0 ${y}L12 ${y+5}L0 ${y+10}Z" fill="currentColor"/>`;
        y+=12;knots-=50;
      }
      while(knots>=10){
        staff+=`<path class="wind-full-barb" d="M0 ${y}l12 -5"/>`;y+=5;knots-=10;
      }
      if(knots>=5)staff+=`<path class="wind-half-barb" d="M0 ${y===-35?y+5:y}l6 -2.5"/>`;
      staff=`<g transform="rotate(${wind.direction})">${staff}</g>`;
    }else if(speed!=null){
      staff=`<text class="variable-wind" x="12" y="4" stroke="none" font-size="10">${wind.variable?"VRB":"?"}</text>`;
    }
    const ranks={CLR:0,SKC:0,FEW:1,SCT:2,BKN:3,OVC:4};
    const known=(station.layers||[]).map(l=>ranks[l.cover]).filter(r=>r!=null);
    const cover=known.length?Math.max(...known):null;
    const fills=["",'<path d="M0 0V-7A7 7 0 0 1 7 0Z"/>','<path d="M0 -7A7 7 0 0 1 0 7Z"/>','<path d="M0 0V-7A7 7 0 1 1 -7 0Z"/>','<circle r="7"/>'];
    const fill=cover!=null?fills[cover]:station.isMetro?"":'<text x="0" y="4" text-anchor="middle" font-size="11">?</text>';
    return `<svg class="metar-plot" width="110" height="100" viewBox="0 0 110 100" aria-hidden="true"><g transform="translate(60 50)" color="#233b31"><g fill="none" stroke="currentColor" stroke-width="1.5">${staff}</g><circle r="7" fill="white" stroke="currentColor" stroke-width="1.5"/><g fill="currentColor">${fill}</g></g><text class="plot-temp" x="46" y="43" text-anchor="end">${rounded(station.tempF)}</text><text class="plot-dew" x="46" y="66" text-anchor="end">${rounded(station.dewpointF)}</text></svg>`;
  }
  function initMetars() {
    if(metarMap)return;
    metarMap=L.map("metar-cloud-map",{minZoom:5,maxZoom:13}).setView([44.925,-93.462],8);
    for(const [kind,opacity] of [["uscounties",.35],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(metarMap);
    markers=L.layerGroup().addTo(metarMap);
    const density=()=>el("metar-cloud-map").classList.toggle("compact-clouds",metarMap.getZoom()<8);
    metarMap.on("zoomend",density);
    metarMap.on("moveend",renderMetars);density();
  }
  function plotStations(stations, metro) {
    const candidates=stations.filter(s=>!metroSites.has(s.station));
    if(metro)candidates.push(metro);
    const priority=s=>{const rank=preferred.indexOf(s.station);return rank<0?preferred.length:rank;};
    candidates.sort((a,b)=>priority(a)-priority(b)||a.station.localeCompare(b.station));
    const size=metarMap.getSize(),accepted=[],points=[];
    for(const station of candidates){
      const point=metarMap.latLngToContainerPoint([station.lat,station.lon]);
      if(point.x<0||point.y<0||point.x>size.x||point.y>size.y)continue;
      if(points.some(p=>Math.abs(p.x-point.x)<90&&Math.abs(p.y-point.y)<65))continue;
      points.push(point);accepted.push(station);
    }
    return accepted;
  }
  function renderMetars() {
    if(!cloudData)return;
    initMetars();markers.clearLayers();
    const hours=timeline();
    metarIndex=Math.max(0,Math.min(metarIndex,hours.length-1));
    const selected=hours[metarIndex],stations=selected.stations,plots=mode()==="plots";
    const drawn=plots?plotStations(stations,selected.metro):stations.filter(ceilingLayer);
    const slider=el("metar-cloud-timeline");
    slider.max=String(hours.length-1);slider.value=String(metarIndex);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*metarIndex/(hours.length-1):0}%`);
    el("metar-cloud-time").textContent=selected.isLive?`Live · checked ${time.format(new Date(cloudData.checkedAt))}`:`${time.format(new Date(selected.hour))} · hourly ${metarIndex+1}/${cloudData.history.length}`;
    slider.setAttribute("aria-valuetext",el("metar-cloud-time").textContent);
    el("metar-heading").textContent=plots?"METAR plots":"Cloud ceilings";
    el("metar-timeline-description").textContent=plots?"Last 12 routine hourly snapshots":"Last 12 hourly snapshots + Live";
    slider.setAttribute("aria-label",plots?"Manual METAR timeline: last 12 routine hourly snapshots":"Manual METAR timeline: hourly history plus Live");
    el("metar-cloud-map").setAttribute("aria-label",plots?"Temperature, dew point and wind station plots":"Cloud ceiling observations");
    el("metar-cloud-legend").hidden=plots;el("metar-plot-legend").hidden=!plots;
    el("metar-table-values").textContent=plots?"Temp / dew (°F) · wind (kt)":"Coverage / bases (ft AGL)";
    const query=el("metar-cloud-search").value.trim().toUpperCase();el("metar-cloud-rows").replaceChildren();
    for(const s of drawn) {
      const layer=ceilingLayer(s);
      const summary=layer?heights(layer,true):"";
      const description=plots?`${rounded(s.tempF)}°F / ${rounded(s.dewpointF)}°F · ${windText(s.wind)}`:layer?(s.hasCeiling?`${layer.cover==="VV"?"Indefinite ceiling":"Ceiling"}: ${heights(layer)}`:`${covers[layer.cover]||layer.cover} · No ceiling reported`):"Cloud information not reported";
      const glyph=plots?stationModel(s):`<span class="cloud-ceiling-number">${summary}</span>`;
      const icon=L.divIcon({className:plots?"weather-station":"cloud-station",html:glyph,iconSize:plots?[110,100]:[24,24],iconAnchor:plots?[60,50]:[12,12]});
      const popup=node("div",null,"cloud-popup");popup.append(node("strong",s.isMetro?"Metro average · KFCM + KMSP + KMIC":s.station));
      const stamp=plots?(s.weatherTime||s.time):s.time;
      popup.append(node("p",stamp?time.format(new Date(stamp)):"Waiting for all three metro stations"));
      if(plots){
        popup.append(node("p",`Temperature ${rounded(s.tempF)}°F · Dew point ${rounded(s.dewpointF)}°F`),node("p",`Wind from ${windText(s.wind)}`));
        if(s.isMetro&&s.oldestObservedAt&&s.oldestObservedAt!==s.time)popup.append(node("p",`Oldest contributor: ${time.format(new Date(s.oldestObservedAt))}`));
        if(s.isMetro&&!s.available)popup.append(node("p","All three metro stations must supply valid routine hourly observations."));
      }else{
        if(layer)popup.append(node("p",description));
        if(!s.layers.length)popup.append(node("p","Cloud information not reported."));
        for(const cloud of s.layers)popup.append(node("p",`${heights(cloud)}${cloud.baseFtAGL!=null&&cloud.cover!=="VV"?" AGL":""}`));
      }
      L.marker([s.lat,s.lon],{icon,title:`${s.station} · ${description}`,keyboard:true}).bindPopup(popup).addTo(markers);
    }
    const listing=plots?[...(selected.metro?[selected.metro]:[]),...stations.filter(s=>!metroSites.has(s.station))]:drawn;
    for(const s of listing){
      if(query&&!s.station.includes(query)&&!(s.isMetro&&"KFCM KMSP KMIC METRO".includes(query)))continue;
      const row=node("tr"),cell=node("td"),button=node("button",s.isMetro?"Metro average":s.station,"station-link");
      button.addEventListener("click",()=>{metarMap.setView([s.lat,s.lon],10);el("metar-cloud-map").scrollIntoView({behavior:"smooth",block:"center"});});cell.append(button);
      const stamp=plots?(s.weatherTime||s.time):s.time;
      row.append(cell,node("td",stamp?time.format(new Date(stamp)):"Unavailable"),node("td",plots?`${rounded(s.tempF)} / ${rounded(s.dewpointF)} °F · ${windText(s.wind)}`:s.layers.length?s.layers.map(l=>heights(l)).join(" · "):"Not reported"));
      el("metar-cloud-rows").append(row);
    }
    el("metar-cloud-status").textContent=plots?`${drawn.length} spaced plots visible · ${listing.length} sites in the list · routine hourly snapshot${cloudData.stale?" · Background updates delayed":""}`:`${drawn.length} broken/overcast ceilings · ${stations.length} reporting stations · ${selected.isLive?"latest available cloud reports":"routine hourly snapshot"}${cloudData.stale?" · Background updates delayed":""}${cloudData.historyPending?" · New weather history is being prepared":""}`;
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
    }
    catch(e){el("metar-cloud-status").textContent=`${e.message}${cloudData?" Previous reports retained; check their timestamps.":""}`;}
    finally{metarBusy=false;el("refresh-metar-clouds").disabled=false;}
  }

  function select(id) {
    if(id==="metar-clouds"){loadMetars();setTimeout(()=>metarMap?.invalidateSize(),0);}
  }
  el("refresh-metar-clouds").addEventListener("click",loadMetars);
  el("metar-cloud-search").addEventListener("input",renderMetars);
  el("metar-cloud-reset").addEventListener("click",()=>metarMap?.setView([44.925,-93.462],8));
  el("metar-cloud-timeline").addEventListener("input",event=>{metarIndex=Number(event.target.value);renderMetars();});
  el("metar-view").addEventListener("change",renderMetars);
  setInterval(()=>{if(!document.hidden&&!el("metar-clouds").hidden)loadMetars();},60000);
  return {select};
})();
