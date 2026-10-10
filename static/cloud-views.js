"use strict";
// Independent viewers: the original COD satellite map/data are untouched.
window.WeatherCloudViews = (() => {
  const el = id => document.getElementById(id);
  const time = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const covers = {CLR:"Clear below sensor limit",SKC:"Sky clear",FEW:"Few (1–2 eighths)",SCT:"Scattered (3–4 eighths)",BKN:"Broken (5–7 eighths)",OVC:"Overcast (8 eighths)",VV:"Obscured sky",NSC:"No significant cloud",NCD:"No cloud detected",CAVOK:"CAVOK cloud criteria"};
  let metarMap, markers, cloudData, metarBusy = false;
  function node(tag, text, className) { const n=document.createElement(tag); if(text!=null)n.textContent=text; if(className)n.className=className; return n; }
  async function read(url) { const r=await fetch(url,{cache:"no-store"});const d=await r.json();if(!r.ok)throw Error(d.error||"Data unavailable");return d; }
  function heights(layer, compact=false) {
    if(layer.cover==="CLR")return compact?"":"CLR · no clouds detected ≤12,000 ft";
    if(["SKC","NSC","NCD","CAVOK"].includes(layer.cover))return compact?"":`${layer.cover} · ${covers[layer.cover]}`;
    const h=layer.baseFtAGL;
    const base=h==null?(compact?"?":"height unknown"):compact?String(Math.round(h/100)).padStart(3,"0"):`${h.toLocaleString()} ft`;
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
    const now=Date.now();
    const stations=cloudData.stations.filter(s=>now-new Date(s.time).getTime()>=0&&now-new Date(s.time).getTime()<=7200000);
    const query=el("metar-cloud-search").value.trim().toUpperCase();el("metar-cloud-rows").replaceChildren();
    for(const s of stations) {
      const layer=s.layers.find(x=>x.baseFtAGL!=null)||s.layers[0];
      const summary=layer?heights(layer,true):"";
      const delayed=now-new Date(s.time).getTime()>5400000;
      const icon=L.divIcon({className:`cloud-station${delayed?" delayed":""}`,html:`${circle(layer?.cover)}<span class="cloud-station-label">${summary}</span>`,iconSize:[62,24],iconAnchor:[10,12]});
      const popup=node("div",null,"cloud-popup");popup.append(node("strong",s.station),node("p",time.format(new Date(s.time))));
      if(!s.layers.length)popup.append(node("p","Cloud information not reported."));
      for(const cloud of s.layers)popup.append(node("p",`${heights(cloud)}${cloud.baseFtAGL!=null&&cloud.cover!=="VV"?" AGL":""}`));
      if(delayed)popup.append(node("p","Report more than 90 minutes old."));
      L.marker([s.lat,s.lon],{icon,title:`${s.station} · ${layer?heights(layer):"Cloud information not reported"}`,keyboard:true}).bindPopup(popup).addTo(markers);
      if(query&&!s.station.includes(query))continue;
      const row=node("tr");const cell=node("td"),button=node("button",s.station,"station-link");button.addEventListener("click",()=>{metarMap.setView([s.lat,s.lon],10);el("metar-cloud-map").scrollIntoView({behavior:"smooth",block:"center"});});cell.append(button);
      row.append(cell,node("td",time.format(new Date(s.time))),node("td",s.layers.length?s.layers.map(l=>heights(l)).join(" · "):"Not reported"));
      if(delayed)row.classList.add("delayed");el("metar-cloud-rows").append(row);
    }
    el("metar-cloud-status").textContent=`${stations.length} reporting stations · all available sites in the Upper Midwest region · checked ${time.format(new Date(cloudData.checkedAt))}${cloudData.stale?" · Background updates delayed":""}`;
  }
  async function loadMetars() {
    if(metarBusy)return;metarBusy=true;el("refresh-metar-clouds").disabled=true;
    try {cloudData=await read("/api/metar-clouds");renderMetars();}
    catch(e){el("metar-cloud-status").textContent=`${e.message}${cloudData?" Previous reports retained; check their timestamps.":""}`;}
    finally{metarBusy=false;el("refresh-metar-clouds").disabled=false;}
  }

  let altMap, altFrames=[], altLayers=new Map(), altIndex=0, altRequest=0, altBusy=false, altProduct;
  let altBounds=[[43.3,-98.85],[46.9,-89.85]];
  function fitAlt(){
    if(!altMap)return;
    const size=altMap.getSize();if(!size.x||!size.y)return;
    const sw=altMap.project(altBounds[0],0),ne=altMap.project(altBounds[1],0);
    const scales=[size.x/(ne.x-sw.x),size.y/(sw.y-ne.y)];
    const scale=window.matchMedia("(max-width: 600px)").matches?Math.max(...scales):Math.min(...scales);
    altMap.setView(altMap.unproject(sw.add(ne).divideBy(2),0),Math.log2(scale),{animate:false});
  }
  function initAlt() {
    if(altMap)return;
    altMap=L.map("alternate-cloud-map",{minZoom:5,maxZoom:12,zoomSnap:0});
    altMap.createPane("cloud-images");altMap.getPane("cloud-images").style.zIndex=350;
    altMap.createPane("cloud-boundaries");altMap.getPane("cloud-boundaries").style.zIndex=410;altMap.getPane("cloud-boundaries").style.pointerEvents="none";
    for(const [kind,opacity] of [["uscounties",.35],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{pane:"cloud-boundaries",opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(altMap);
    fitAlt();altMap.on("resize",fitAlt);altMap.attributionControl.addAttribution("NOAA GOES-19 cloud products");
  }
  function showAlt(n) {
    if(!altFrames.length)return;
    altIndex=Math.max(0,Math.min(n,altFrames.length-1));
    const selected=altFrames[altIndex];
    for(const [key,layer] of altLayers)layer.setOpacity(key===selected.url?1:0);
    el("alternate-cloud-timeline").value=String(altIndex);
    el("alternate-cloud-timeline").style.setProperty("--progress",`${altFrames.length>1?100*altIndex/(altFrames.length-1):0}%`);
    el("alternate-cloud-time").textContent=`${time.format(new Date(selected.time))} · ${altIndex+1}/${altFrames.length}`;
    el("alternate-cloud-timeline").setAttribute("aria-valuetext",el("alternate-cloud-time").textContent);
  }
  async function loadAlt(force=false) {
    const product=el("alternate-cloud-product").value;
    if(altBusy&&!force&&product===altProduct)return;
    const request=++altRequest,changed=product!==altProduct;
    const selected=altFrames[altIndex]?.time,followLatest=!altFrames.length||altIndex===altFrames.length-1;
    altBusy=true;el("refresh-alternate-clouds").disabled=true;el("alternate-cloud-timeline").disabled=true;
    try {
      initAlt();
      if(changed){for(const layer of altLayers.values())altMap.removeLayer(layer);altLayers.clear();altFrames=[];el("alternate-cloud-time").textContent="Loading NOAA imagery…";}
      altProduct=product;
      const data=await read("/api/alternate-clouds");if(request!==altRequest)return;
      if(data.renderVersion!=="local-clouds-v1")throw Error("Local cloud map is being updated. Refresh shortly.");
      altBounds=data.bounds;
      const info=data.products[product];el("alternate-cloud-description").textContent=info.description;el("alternate-cloud-source").href=data.sourceUrl;
      el("alternate-cloud-legend-tops").hidden=product!=="combined";el("alternate-cloud-legend-optical").hidden=product!=="optical";
      const loaded=[],queue=data.frames.map(f=>({...f,url:f.url.replace("/combined.png",`/${product}.png`)})).reverse();let failed=0,completed=0;
      async function worker() {
        while(queue.length&&request===altRequest&&!document.hidden&&!el("alternate-clouds").hidden){
          const frame=queue.shift();
          try {
            let layer=altLayers.get(frame.url);
            if(!layer){const image=new Image();image.src=frame.url;await image.decode();if(request!==altRequest)return;if(image.naturalWidth!==data.width||image.naturalHeight!==data.height)throw Error("Unexpected cloud image dimensions");layer=L.imageOverlay(image,data.bounds,{opacity:0,pane:"cloud-images",interactive:false}).addTo(altMap);altLayers.set(frame.url,layer);}
            loaded.push(frame);
            if(!altFrames.length){altFrames=[frame];showAlt(0);}
          }catch(e){failed++;}
          completed++;if(request===altRequest)el("alternate-cloud-status").textContent=`Local clouds · preparing history ${completed}/${data.frames.length} scans…`;
        }
      }
      await Promise.all([worker(),worker()]);if(request!==altRequest)return;
      if(!loaded.length)throw Error("NOAA images could not load. Try Refresh images.");
      loaded.sort((a,b)=>a.time.localeCompare(b.time));const keep=new Set(loaded.map(f=>f.url));
      for(const [key,layer] of altLayers)if(!keep.has(key)){altMap.removeLayer(layer);altLayers.delete(key);}
      altFrames=loaded;el("alternate-cloud-timeline").max=String(loaded.length-1);
      const restored=!followLatest&&selected?loaded.findIndex(f=>f.time>=selected):-1;showAlt(restored>=0?restored:loaded.length-1);
      const age=(Date.now()-new Date(loaded.at(-1).time).getTime())/60000;
      const gaps=new Date(loaded[0].time)-new Date(data.windowStart)>10*60000||loaded.some((f,i)=>i&&new Date(f.time)-new Date(loaded[i-1].time)>10*60000);
      el("alternate-cloud-status").textContent=`${info.label} · ${loaded.length} scans in the past two hours${failed?` · ${failed} scans unavailable`:""}${gaps?" · Some scans are missing":""}${age>20?` · Latest scan ${Math.round(age)} minutes old`:""} · Experimental NOAA view`;
    }catch(e){if(request===altRequest)el("alternate-cloud-status").textContent=`${e.message} The original Satellite tab remains available.`;}
    finally{if(request===altRequest){altBusy=false;el("refresh-alternate-clouds").disabled=false;el("alternate-cloud-timeline").disabled=altFrames.length<2;}}
  }
  function select(id) {
    if(id==="metar-clouds"){loadMetars();setTimeout(()=>metarMap?.invalidateSize(),0);}
    if(id==="alternate-clouds"){loadAlt();setTimeout(()=>altMap?.invalidateSize(),0);}
    else{++altRequest;altBusy=false;el("refresh-alternate-clouds").disabled=false;}
  }
  el("refresh-metar-clouds").addEventListener("click",loadMetars);
  el("metar-cloud-search").addEventListener("input",renderMetars);
  el("metar-cloud-reset").addEventListener("click",()=>metarMap?.setView([44.925,-93.462],8));
  el("refresh-alternate-clouds").addEventListener("click",()=>loadAlt(true));
  el("alternate-cloud-product").addEventListener("change",()=>loadAlt(true));
  el("alternate-cloud-timeline").addEventListener("input",event=>showAlt(Number(event.target.value)));
  el("alternate-cloud-reset").addEventListener("click",fitAlt);
  setInterval(()=>{if(document.hidden)return;if(!el("metar-clouds").hidden)loadMetars();if(!el("alternate-clouds").hidden)loadAlt();},60000);
  return {select};
})();
