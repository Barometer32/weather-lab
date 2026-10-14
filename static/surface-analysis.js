"use strict";
window.WeatherSurfaceViews = (() => {
  const el=id=>document.getElementById(id);
  const stamp=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const labels={tempF:"Temperature",dewpointF:"Dew point",wind:"Wind"};
  let map,layers,frame,data,analysis,request=0,currentUrl;
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
  function coverage(){
    const body=el("surface-coverage");body.replaceChildren();
    const counts=new Map();for(const row of frame.stations)counts.set(row.network,(counts.get(row.network)||0)+1);
    const networks=new Map((data.coverage||[]).map(r=>[r.network,r.available]));
    for(const network of counts.keys())if(!networks.has(network))networks.set(network,null);
    for(const [network,available] of [...networks].sort((a,b)=>a[0].localeCompare(b[0]))){const tr=node("tr");tr.append(node("td",network),node("td",available??"—"),node("td",counts.get(network)||0));body.append(tr);}
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
    if(el("surface-points").checked)for(const station of frame.stations){
      const qc=station.analysisQc?.[field]||{status:"unverified",reason:"No local neighborhood check available"};
      const speed=station.wind?.speedMph??(station.wind?.speedKnots==null?null:station.wind.speedKnots*1.150779448);
      const value=field==="wind"?speed:station[field];
      if(value==null)continue;
      const excluded=qc.status==="suspect"||qc.status==="missing";
      const p=node("div");p.append(node("strong",`${station.station} · ${station.name||station.network}`),node("p",`${labels[field]} ${value.toFixed(1)} ${unit}`),node("p",`${station.network} · ${stamp.format(new Date(station.time))}`),node("p",`${excluded?"Excluded":"Included if spatially supported"}: ${qc.status}. ${qc.reason}`));
      if(qc.difference!=null&&qc.tolerance!=null)p.append(node("p",`Neighbor comparison: ${qc.difference.toFixed(1)} ${unit} difference · ${qc.tolerance.toFixed(1)} ${unit} threshold · ${qc.neighbors} neighbor groups`));
      L.circleMarker([station.lat,station.lon],{radius:excluded?3.5:2.5,color:excluded?"#69706f":"#fff",weight:1,fillColor:excluded?"#69706f":"#203b35",fillOpacity:.9}).bindPopup(p).addTo(layers);
    }
    const bar=node("div");bar.className="surface-gradient";
    const palette=product.palette,low=palette[0][0],span=palette.at(-1)[0]-low;
    const banded=product.paletteMode==="discrete";
    const colorStops=banded?palette.slice(0,-1).flatMap(([v,c],i)=>[`${c} ${100*(v-low)/span}%`,`${c} ${100*(palette[i+1][0]-low)/span}%`]):palette.map(([v,c])=>`${c} ${100*(v-low)/span}%`);
    bar.style.background=`linear-gradient(to right,${colorStops.join(",")})`;
    bar.setAttribute("aria-label",`${labels[field]} color scale${banded?", 5-degree Fahrenheit bands":""}`);
    const ticks=node("div");ticks.className="surface-ticks";
    for(const [v] of palette){if(banded&&v%10!==0&&v!==palette.at(-1)[0])continue;const tick=node("span",String(v));tick.style.left=`${100*(v-low)/span}%`;ticks.append(tick);}
    el("surface-legend").append(node("strong",`${labels[field]} · ${unit}${banded?" · 5°F bands":""}`),bar,ticks);
    if(banded){const note=node("p",field==="dewpointF"?"White: dew points below 20°F. Other bands change every 5°F.":"White: temperatures below −20°F or at least 105°F, following the reference scale.");note.className="small-note";el("surface-legend").append(note);}
    const qc=product.qc||{};
    el("surface-status").textContent=`${stamp.format(new Date(analysis.hour))} · ${product.used} spatially spaced inputs · ${qc.suspect||0} suspect fields excluded · ${qc.unverified||0} fields with limited neighbor checks${product.supportedCells?" · Blank areas have insufficient observations":" · Not enough observations for contours"}`;
    setTimeout(()=>map.invalidateSize(),0);
  }
  async function setFrame(selected,dataset){
    if(frame===selected&&data===dataset)return;
    frame=selected;data=dataset;coverage();
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
  el("surface-field").addEventListener("change",render);
  el("surface-points").addEventListener("change",render);
  el("surface-reset").addEventListener("click",()=>{init();reset();});
  return {setFrame};
})();
