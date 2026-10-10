"use strict";
// Hourly airport clouds; the original COD satellite viewer is independent.
window.WeatherCloudViews = (() => {
  const el = id => document.getElementById(id);
  const time = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const covers = {CLR:"Clear below sensor limit",SKC:"Sky clear",FEW:"Few (1–2 eighths)",SCT:"Scattered (3–4 eighths)",BKN:"Broken (5–7 eighths)",OVC:"Overcast (8 eighths)",VV:"Obscured sky",NSC:"No significant cloud",NCD:"No cloud detected",CAVOK:"CAVOK cloud criteria"};
  let metarMap, markers, cloudData, metarBusy = false, metarIndex = 0;
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
  function circle(cover) {
    const fraction={FEW:.25,SCT:.5,BKN:.75,OVC:1}[cover]||0;
    let fill="";
    if(fraction===1)fill='<circle cx="10" cy="10" r="7" fill="#176741"/>';
    else if(fraction) { const a=-Math.PI/2+2*Math.PI*fraction,x=10+7*Math.cos(a),y=10+7*Math.sin(a);fill=`<path d="M10 10 L10 3 A7 7 0 ${fraction>.5?1:0} 1 ${x} ${y} Z" fill="#176741"/>`; }
    const unknown=!cover||["VV","NSC","NCD","CAVOK"].includes(cover);
    return `<svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7" fill="white" stroke="#233b31" stroke-width="1.7"/>${fill}${unknown?'<text x="10" y="14" text-anchor="middle" font-size="12">?</text>':""}</svg>`;
  }
  function initMetars() {
    if(metarMap)return;
    metarMap=L.map("metar-cloud-map",{minZoom:5,maxZoom:13}).setView([44.925,-93.462],8);
    for(const [kind,opacity] of [["uscounties",.35],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(metarMap);
    markers=L.layerGroup().addTo(metarMap);
    const density=()=>el("metar-cloud-map").classList.toggle("compact-clouds",metarMap.getZoom()<8);
    metarMap.on("zoomend",density);density();
  }
  function renderMetars() {
    if(!cloudData)return;
    initMetars();markers.clearLayers();
    const hours=cloudData.history;
    if(!hours.length)return;
    metarIndex=Math.max(0,Math.min(metarIndex,hours.length-1));
    const selected=hours[metarIndex],stations=selected.stations;
    const slider=el("metar-cloud-timeline");
    slider.max=String(hours.length-1);slider.value=String(metarIndex);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*metarIndex/(hours.length-1):0}%`);
    el("metar-cloud-time").textContent=`${time.format(new Date(selected.hour))} · ${metarIndex+1}/${hours.length}`;
    slider.setAttribute("aria-valuetext",el("metar-cloud-time").textContent);
    const query=el("metar-cloud-search").value.trim().toUpperCase();el("metar-cloud-rows").replaceChildren();
    for(const s of stations) {
      const layer=s.layers.find(x=>x.baseFtAGL!=null)||s.layers[0];
      const summary=layer?heights(layer,true):"";

      const icon=L.divIcon({className:"cloud-station",html:`${circle(layer?.cover)}<span class="cloud-station-label">${summary}</span>`,iconSize:[62,24],iconAnchor:[10,12]});
      const popup=node("div",null,"cloud-popup");popup.append(node("strong",s.station),node("p",time.format(new Date(s.time))));
      if(!s.layers.length)popup.append(node("p","Cloud information not reported."));
      for(const cloud of s.layers)popup.append(node("p",`${heights(cloud)}${cloud.baseFtAGL!=null&&cloud.cover!=="VV"?" AGL":""}`));
      L.marker([s.lat,s.lon],{icon,title:`${s.station} · ${layer?heights(layer):"Cloud information not reported"}`,keyboard:true}).bindPopup(popup).addTo(markers);
      if(query&&!s.station.includes(query))continue;
      const row=node("tr");const cell=node("td"),button=node("button",s.station,"station-link");button.addEventListener("click",()=>{metarMap.setView([s.lat,s.lon],10);el("metar-cloud-map").scrollIntoView({behavior:"smooth",block:"center"});});cell.append(button);
      row.append(cell,node("td",time.format(new Date(s.time))),node("td",s.layers.length?s.layers.map(l=>heights(l)).join(" · "):"Not reported"));
      el("metar-cloud-rows").append(row);
    }
    el("metar-cloud-status").textContent=`${stations.length} routine reporting stations for this hour${stations.length?"":" · No routine reports available"} · checked ${time.format(new Date(cloudData.checkedAt))}${cloudData.stale?" · Background updates delayed":""}`;
  }
  async function loadMetars() {
    if(metarBusy)return;metarBusy=true;el("refresh-metar-clouds").disabled=true;
    try {
      const data=await read("/api/metar-clouds");
      const selected=cloudData?.history[metarIndex]?.hour;
      const followLatest=!cloudData||metarIndex===cloudData.history.length-1;
      cloudData=data;
      const restored=!followLatest&&selected?data.history.findIndex(h=>h.hour===selected):-1;
      metarIndex=restored>=0?restored:followLatest?data.history.length-1:0;
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
  function scheduleHourly() {
    const now=new Date(), next=[3,56,59].map(minute=>{
      const date=new Date(now);date.setUTCMinutes(minute,20,0);if(date<=now)date.setUTCHours(date.getUTCHours()+1);return date.getTime();
    });
    setTimeout(()=>{if(!document.hidden&&!el("metar-clouds").hidden)loadMetars();scheduleHourly();},Math.min(...next)-now.getTime());
  }
  scheduleHourly();
  return {select};
})();
