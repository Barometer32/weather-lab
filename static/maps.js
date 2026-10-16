"use strict";
window.WeatherMaps = (() => {
  const el=id=>document.getElementById(id);
  const stamp=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const labels={tempF:"Temperature",dewpointF:"Dew point",wind:"Wind speed and direction"};
  const selectedHours=new Map(),cache=new Map();
  let map,layers,data,frame,analysis,index=0,request=0,currentUrl,busy=false;
  let playing=false,playTimer,generation=0,hourTimer,retryTimer,waitUntil=0;
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  const visible=()=>!document.hidden&&!el("maps").hidden;
  function reset(){map.fitBounds([[42.3,-98],[49.4,-88.5]]);}
  function init(){
    if(map)return;
    map=L.map("surface-map",{minZoom:5,maxZoom:12});reset();
    map.createPane("mapsRaster").style.zIndex=250;
    map.createPane("mapsBoundaries").style.zIndex=450;
    map.getPane("mapsBoundaries").style.pointerEvents="none";
    for(const [kind,opacity] of [["uscounties",.25],["usstates",.9]]){
      L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{pane:"mapsBoundaries",opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(map);
    }
    layers=L.layerGroup().addTo(map);
  }
  function timeline(){
    const slider=el("surface-timeline"),hours=data.history;
    slider.max=String(hours.length-1);slider.value=String(index);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*index/(hours.length-1):0}%`);
    el("surface-time").textContent=`${stamp.format(new Date(frame.hour))} · hour ${index+1}/${hours.length}`;
    slider.setAttribute("aria-valuetext",el("surface-time").textContent);
    el("surface-play").disabled=hours.length<2;
    el("surface-feed-status").textContent=`${frame.stationCount} eligible airport METARs · :50–:59 reports · collected hourly at :02${data.stale?" · Hourly update delayed; showing saved maps":""}`;
  }
  function render(){
    init();layers.clearLayers();el("surface-legend").replaceChildren();
    if(!analysis)return;
    const field=el("surface-field").value,product=analysis.fields[field];
    if(!product)throw Error("This field is not prepared for the selected hour");
    const unit=field==="wind"?"mph":"°F";
    L.imageOverlay(product.imageUrl,analysis.bounds,{pane:"mapsRaster",opacity:1,interactive:false}).on("error",()=>{
      el("surface-status").textContent="The map image could not load. Select another hour or refresh.";
    }).addTo(layers);
    const labeled=new Set();
    L.geoJSON(product.contours,{style:{color:"#233940",weight:.8,opacity:.65},onEachFeature:(feature,line)=>{
      const level=feature.properties.value,permanent=!labeled.has(level)&&feature.geometry.coordinates.length>12;
      if(permanent)labeled.add(level);
      line.bindTooltip(permanent?String(level):`${labels[field]} ${level} ${unit}`,{sticky:!permanent,permanent,direction:"center",className:permanent?"surface-contour-label":""});
    }}).addTo(layers);
    for(const arrow of product.arrows||[]){
      const toward=(arrow.direction+180)%360;
      const path="M0 10V-10M-3 -6L0 -11L3 -6";
      const icon=L.divIcon({className:"surface-wind",iconSize:[28,28],iconAnchor:[14,14],html:`<svg width="28" height="28" viewBox="-14 -14 28 28" aria-hidden="true"><g transform="rotate(${toward})" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="${path}" stroke="white" stroke-width="3.5"/><path d="${path}" stroke="#203540" stroke-width="1.5"/></g></svg>`});
      L.marker([arrow.lat,arrow.lon],{icon,interactive:false,keyboard:false}).addTo(layers);
    }
    const palette=product.palette,low=palette[0][0],span=palette.at(-1)[0]-low;
    const bar=node("div"),ticks=node("div");bar.className="surface-gradient";ticks.className="surface-ticks";
    const stops=palette.slice(0,-1).flatMap(([v,c],i)=>[`${c} ${100*(v-low)/span}%`,`${c} ${100*(palette[i+1][0]-low)/span}%`]);
    bar.style.background=`linear-gradient(to right,${stops.join(",")})`;
    bar.setAttribute("aria-label",`${labels[field]} color scale, 5 ${unit} bands`);
    for(const [v] of palette){
      if(field!=="wind"&&v%10!==0&&v!==palette.at(-1)[0])continue;
      const tick=node("span",String(v));tick.style.left=`${100*(v-low)/span}%`;ticks.append(tick);
    }
    el("surface-legend").append(node("strong",`${labels[field]} · ${unit} · 5 ${unit} bands`),bar,ticks);
    if(field!=="wind")el("surface-legend").append(node("p","Temperature and dew point use identical colors at the same Fahrenheit values."));
    const qc=product.qc||{};
    el("surface-status").textContent=`${product.used} spatially spaced inputs · ${qc.suspect||0} suspect values excluded · ${qc.unverified||0} inputs with limited neighbor checks · ${product.supportedCells?"Blank areas have insufficient observations":"Insufficient observations for a supported map"}`;
    setTimeout(()=>map.invalidateSize(),0);
  }
  async function selectFrame(position){
    if(!data?.history?.length)return;
    index=Math.max(0,Math.min(position,data.history.length-1));frame=data.history[index];
    selectedHours.set(el("surface-field").value,frame.hour);timeline();
    const url=frame.analysisUrl;
    if(url===currentUrl&&analysis){render();return;}
    currentUrl=url;analysis=null;const token=++request,selected=frame;
    init();layers.clearLayers();el("surface-legend").replaceChildren();
    if(!url){el("surface-status").textContent="No eligible reports or prepared map for this hour. Saved observations are never filled with invented readings.";return;}
    el("surface-status").textContent="Loading hourly map…";
    try{
      let result=cache.get(url);
      if(!result){
        const response=await fetch(url);if(!response.ok)throw Error("Map temporarily unavailable");
        result=await response.json();
        if(result.hour!==selected.hour)throw Error("Map time does not match the selected hour");
        cache.set(url,result);if(cache.size>12)cache.delete(cache.keys().next().value);
      }
      if(token!==request)return;
      analysis=result;render();
    }catch(error){if(token===request)el("surface-status").textContent=error.message;}
  }
  function stop(){playing=false;generation++;clearTimeout(playTimer);el("surface-play").textContent="Play";el("surface-play").setAttribute("aria-pressed","false");}
  async function tick(version){
    if(!playing||version!==generation)return;
    if(!visible()){stop();return;}
    await selectFrame((index+1)%data.history.length);
    if(playing&&version===generation)playTimer=setTimeout(()=>tick(version),1100);
  }
  function retry(){
    clearTimeout(retryTimer);
    if(Date.now()<waitUntil)retryTimer=setTimeout(()=>{if(visible())load();},60000);
  }
  async function load(){
    if(busy)return;busy=true;el("refresh-maps").disabled=true;
    try{
      const response=await fetch("/api/maps",{cache:"no-store"}),fresh=await response.json();
      if(!response.ok)throw Error(fresh.error||"Maps temporarily unavailable");
      if(!fresh.history?.length)throw Error("Map history is still preparing");
      const previous=data;data=fresh;
      for(const field of Object.keys(labels)){
        const saved=selectedHours.get(field);
        if(!saved||saved===previous?.history.at(-1)?.hour)selectedHours.set(field,data.history.at(-1).hour);
        else if(!data.history.some(f=>f.hour===saved))selectedHours.set(field,data.history[0].hour);
      }
      await selectFrame(data.history.findIndex(f=>f.hour===selectedHours.get(el("surface-field").value)));
      const now=new Date(),due=new Date(now);due.setUTCMinutes(2,0,0);
      if(due>now)due.setUTCHours(due.getUTCHours()-1);
      if(new Date(data.checkedAt)<due)retry();else{waitUntil=0;clearTimeout(retryTimer);}
    }catch(error){el("surface-status").textContent=`${error.message}${data?" Saved maps retained.":""}`;retry();}
    finally{busy=false;el("refresh-maps").disabled=false;}
  }
  function schedule(){
    clearTimeout(hourTimer);
    const interval=3600000,offset=2*60000+30000,now=Date.now();
    hourTimer=setTimeout(()=>{if(visible()){waitUntil=Date.now()+5*60000;load();}schedule();},(Math.floor((now-offset)/interval)+1)*interval+offset-now);
  }
  function select(id){
    if(id!=="maps"){stop();return;}
    init();waitUntil=Date.now()+5*60000;load();setTimeout(()=>map.invalidateSize(),0);
  }
  el("surface-field").addEventListener("change",()=>{stop();if(data)selectFrame(data.history.findIndex(f=>f.hour===selectedHours.get(el("surface-field").value)));});
  el("surface-timeline").addEventListener("input",event=>{stop();selectFrame(Number(event.target.value));});
  el("surface-play").addEventListener("click",()=>{if(playing){stop();return;}if(!data||data.history.length<2)return;playing=true;el("surface-play").textContent="Pause";el("surface-play").setAttribute("aria-pressed","true");tick(++generation);});
  el("surface-reset").addEventListener("click",()=>{init();reset();});
  el("refresh-maps").addEventListener("click",()=>{waitUntil=Date.now()+5*60000;load();});
  document.addEventListener("visibilitychange",()=>{if(document.hidden)stop();else if(!el("maps").hidden)select("maps");});
  schedule();
  return {select};
})();
