"use strict";
window.WeatherSurfaceViews = (() => {
  const el=id=>document.getElementById(id);
  const stamp=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const labels={tempF:"Temperature",dewpointF:"Dew point",wind:"Wind"};
  let map,layers,frame,data,analysis,request=0,currentUrl,index=0,playing=false,playTimer,playGeneration=0;
  const selectedHours=new Map();
  const cache=new Map();
  function node(tag,text){const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;}
  function reset(){map.fitBounds([[43,-97.5],[49.4,-88.5]]);}
  function init(){
    if(map)return;
    map=L.map("surface-map",{minZoom:5,maxZoom:13});reset();
    map.createPane("analysisRaster").style.zIndex=250;
    map.createPane("analysisBoundaries").style.zIndex=450;
    map.getPane("analysisBoundaries").style.pointerEvents="none";
    for(const [kind,opacity] of [["uscounties",.25],["usstates",.9]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{pane:"analysisBoundaries",opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(map);
    layers=L.layerGroup().addTo(map);
  }
  function isAirport(network){return network?.endsWith("_ASOS")||network==="AWC_METAR";}
  function showHealth(selected,dataset,target="surface-feed-status"){
    const box=el(target);if(!box)return;
    box.hidden=false;box.replaceChildren();
    const rows=selected.stations||[],counts=new Map();
    for(const row of rows)counts.set(row.network,(counts.get(row.network)||0)+1);
    const expected=selected.networkHealth?.map(r=>r.network)||dataset.expectedNetworks||(dataset.coverage||[]).map(r=>r.network);
    const missing=expected.filter(n=>n!=="AWC_METAR"&&!counts.get(n));
    const checks=selected.sourceHealth||(selected.hour===dataset.hour?dataset.sourceHealth:null);
    const failed=(checks||[]).filter(s=>s.status==="failed").map(s=>/^[A-Z]{2}$/.test(s.source)?`IEM ${s.source}`:s.source);
    const airports=rows.filter(r=>isAirport(r.network)).length;
    const wisconet=counts.get("WISCONET")||0,mesonet=rows.length-airports-wisconet;
    const issues=[];
    if(!airports)issues.push("ASOS / airport METARs: no eligible reports");
    if(!mesonet)issues.push("Mesonet / road stations: no eligible reports");
    if(missing.length)issues.push(`Networks with zero reports: ${missing.join(", ")}`);
    if(failed.length)issues.push(`Feed download failed: ${failed.join(", ")}`);
    const awc=(checks||[]).find(s=>s.source==="AWC METAR");
    if(awc?.status==="ok"&&!awc.reports)issues.push("NOAA AWC: no eligible routine METARs; airport counts may include IEM fallback");
    if(selected.hour===dataset.hour&&dataset.stale)issues.push("Hourly collection is delayed; showing the saved time");
    box.className=`feed-health ${issues.length?"feed-health-warning":checks?"feed-health-reporting":"feed-health-unknown"}`;
    box.append(node("strong",issues.length?"Observation coverage · missing data":checks?"Observation coverage · reporting":"Observation coverage · saved counts only"));
    box.append(node("p",`ASOS / airports: ${airports} · Mesonet / road: ${mesonet} · Wisconet: ${wisconet} eligible sites`));
    for(const issue of issues)box.append(node("p",issue));
    if(selected.hour===dataset.hour&&(dataset.delayedNetworks||[]).length)box.append(node("p",`Late reports: ${dataset.delayedNetworks.join(", ")}. Earlier hours fill in on hourly updates.`));
    if(!checks)box.append(node("p","Feed download status was not recorded for this saved hour; counts show received observations only."));
    box.append(node("p","Checks whole-network presence within this hour’s :30–:59 window, not every station or the complete MADIS catalog."));
  }
  function coverage(){
    const body=el("surface-coverage");body.replaceChildren();
    const counts=new Map();for(const row of frame.stations)counts.set(row.network,(counts.get(row.network)||0)+1);
    const available=new Map(frame.hour===data.hour?(data.coverage||[]).map(r=>[r.network,r.available]):[]);
    const networks=new Set([...(frame.networkHealth||[]).map(r=>r.network),...(data.expectedNetworks||[]),...counts.keys()]);
    for(const network of [...networks].sort()){
      const tr=node("tr"),count=counts.get(network)||0;
      tr.append(node("td",network),node("td",available.get(network)??"—"),node("td",count),node("td",count?"Reporting":"No eligible reports"));body.append(tr);
    }
    showHealth(frame,data);
  }
  function timeline(){
    const slider=el("surface-timeline"),hours=data.history;
    slider.max=String(hours.length-1);slider.value=String(index);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*index/(hours.length-1):0}%`);
    el("surface-time").textContent=`${stamp.format(new Date(frame.hour))} · hourly ${index+1}/${hours.length}`;
    slider.setAttribute("aria-valuetext",el("surface-time").textContent);
    el("surface-play").disabled=hours.length<2;
  }
  function render(){
    init();layers.clearLayers();el("surface-legend").replaceChildren();
    if(!analysis)return;
    const field=el("surface-field").value,product=analysis.fields[field];
    if(!product)return;
    const unit=field==="wind"?"mph":"°F";
    L.imageOverlay(product.imageUrl,analysis.bounds,{pane:"analysisRaster",opacity:1,interactive:false}).on("error",()=>{el("surface-status").textContent="The analysis image could not load. Select another hour or refresh.";}).addTo(layers);
    const labeled=new Set();
    L.geoJSON(product.contours,{style:{color:"#233940",weight:.8,opacity:.65},onEachFeature:(feature,line)=>{
      const level=feature.properties.value,permanent=level%5===0&&!labeled.has(level)&&feature.geometry.coordinates.length>12;
      if(permanent)labeled.add(level);
      line.bindTooltip(permanent?`${level}`:`${labels[field]} ${level} ${unit}`,{sticky:!permanent,permanent,direction:"center",className:permanent?"surface-contour-label":""});
    }}).addTo(layers);
    for(const arrow of product.arrows||[]){
      const toward=(arrow.direction+180)%360;
      const icon=L.divIcon({className:"surface-wind",iconSize:[20,28],iconAnchor:[10,14],html:`<svg width="20" height="28" viewBox="-10 -14 20 28" aria-hidden="true"><g transform="rotate(${toward})" fill="none" stroke="#203540" stroke-width="1.4"><path d="M0 11V-11M-3 -6L0 -11L3 -6"/></g></svg>`});
      L.marker([arrow.lat,arrow.lon],{icon,interactive:false,keyboard:false}).addTo(layers);
    }
    const bar=node("div");bar.className="surface-gradient";
    const palette=product.palette,low=palette[0][0],span=palette.at(-1)[0]-low;
    const banded=product.paletteMode==="discrete";
    const colorStops=banded?palette.slice(0,-1).flatMap(([v,c],i)=>[`${c} ${100*(v-low)/span}%`,`${c} ${100*(palette[i+1][0]-low)/span}%`]):palette.map(([v,c])=>`${c} ${100*(v-low)/span}%`);
    bar.style.background=`linear-gradient(to right,${colorStops.join(",")})`;
    bar.setAttribute("aria-label",`${labels[field]} color scale${banded?field==="wind"?", 5-mile-per-hour bands":", 5-degree Fahrenheit bands":""}`);
    const ticks=node("div");ticks.className="surface-ticks";
    for(const [v] of palette){if(banded&&field!=="wind"&&v%10!==0&&v!==palette.at(-1)[0])continue;const tick=node("span",String(v));tick.style.left=`${100*(v-low)/span}%`;ticks.append(tick);}
    el("surface-legend").append(node("strong",`${labels[field]} · ${unit}${banded?field==="wind"?" · 5 mph bands":" · 5°F bands":""}`),bar,ticks);
    if(banded&&field!=="wind"){const note=node("p","Temperature and dew point share identical colors at every 5°F interval. White: below −20°F or at least 105°F.");note.className="small-note";el("surface-legend").append(note);}
    const qc=product.qc||{};
    const delayed=frame.hour===data.hour&&(data.delayedNetworks||[]).includes("MN_RWIS")?" · Minnesota road reports delayed; earlier hours fill in on hourly updates":"";
    el("surface-status").textContent=`${stamp.format(new Date(analysis.hour))} ${delayed} · ${product.used} spatially spaced inputs · ${qc.suspect||0} suspect fields excluded · ${qc.unverified||0} fields with limited neighbor checks${product.supportedCells?" · Blank areas have insufficient observations":" · Not enough observations for contours"}`;
    setTimeout(()=>map.invalidateSize(),0);
  }
  async function selectFrame(position){
    if(!data?.history?.length)return;
    index=Math.max(0,Math.min(position,data.history.length-1));
    frame=data.history[index];selectedHours.set(el("surface-field").value,frame.hour);
    timeline();coverage();
    const selected=frame;
    const url=selected.analysisUrl;
    if(url===currentUrl&&analysis){render();return;}
    currentUrl=url;analysis=null;const token=++request;
    init();layers.clearLayers();el("surface-legend").replaceChildren();
    if(!url){el("surface-status").textContent=`${stamp.format(new Date(selected.hour))} · No prepared contours for this hour. New maps build with each hourly collection.`;return;}
    el("surface-status").textContent="Loading hourly surface analysis…";
    try{
      let result=cache.get(url);
      if(!result){const response=await fetch(url);if(!response.ok)throw Error("Surface analysis temporarily unavailable");result=await response.json();cache.set(url,result);if(cache.size>12)cache.delete(cache.keys().next().value);}
      if(token!==request)return;
      if(result.hour!==frame.hour)throw Error("Surface analysis time does not match the selected hour");
      analysis=result;render();
    }catch(error){if(token===request)el("surface-status").textContent=error.message;}
  }
  function stop(){playing=false;playGeneration++;clearTimeout(playTimer);el("surface-play").textContent="Play";el("surface-play").setAttribute("aria-pressed","false");}
  async function tick(generation){
    if(!playing||generation!==playGeneration)return;
    if(document.hidden||el("metar-clouds").hidden){stop();return;}
    await selectFrame((index+1)%data.history.length);
    if(playing&&generation===playGeneration)playTimer=setTimeout(()=>tick(generation),1100);
  }
  async function setData(dataset){
    if(data===dataset||!dataset?.history?.length)return;
    const previous=data;stop();data=dataset;
    for(const field of Object.keys(labels)){
      const saved=selectedHours.get(field);
      if(!saved||saved===previous?.history.at(-1)?.hour)selectedHours.set(field,data.history.at(-1).hour);
      else if(!data.history.some(h=>h.hour===saved))selectedHours.set(field,data.history[0].hour);
    }
    await selectFrame(data.history.findIndex(h=>h.hour===selectedHours.get(el("surface-field").value)));
  }
  el("surface-field").addEventListener("change",()=>{stop();if(data)selectFrame(data.history.findIndex(h=>h.hour===selectedHours.get(el("surface-field").value)));});
  el("surface-timeline").addEventListener("input",event=>{stop();selectFrame(Number(event.target.value));});
  el("surface-play").addEventListener("click",()=>{
    if(playing){stop();return;}
    if(!data||data.history.length<2)return;
    playing=true;el("surface-play").textContent="Pause";el("surface-play").setAttribute("aria-pressed","true");tick(++playGeneration);
  });
  document.addEventListener("visibilitychange",()=>{if(document.hidden)stop();});
  el("surface-reset").addEventListener("click",()=>{init();reset();});
  return {setData,showHealth};
})();
