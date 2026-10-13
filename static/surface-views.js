"use strict";
window.WeatherSurfaceViews=(()=>{
  const el=id=>document.getElementById(id),C=SurfaceCore;
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const qcNames={V:"MADIS verified",S:"MADIS screened",C:"MADIS validity checks",METAR:"Routine METAR; local checks",LOCAL:"Local checks only",Z:"Not checked",Q:"MADIS questioned",B:"MADIS rejected",X:"MADIS invalid"};
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  let map,markers,lines,vectors,image,worker,manifest,data,frameIndex=11,busy=false,requestId=0,jobId=0,renderTimer,refreshTimer,retryTimer,waitUntil=0,lastResult;
  const payloads=new Map(),mode=()=>el("surface-field").value,source=()=>el("surface-source").value,quality=()=>el("surface-quality").value;
  const rounded=x=>Number.isFinite(x)?String(Math.round(x)):"—";
  const node=(tag,text,className)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(className)n.className=className;return n;};
  async function read(url){const r=await fetch(url,{cache:url==="/api/surface"?"no-store":"default"});const d=await r.json();if(!r.ok)throw Error(d.error||"Surface data unavailable");return d;}
  function init(){
    if(map)return;
    map=L.map("surface-map",{minZoom:4,maxZoom:13,zoomSnap:.1,zoomDelta:.1});reset();
    el("surface-comparison").open=map.getSize().x>=600;
    map.createPane("surface-analysis");map.getPane("surface-analysis").style.zIndex=320;map.getPane("surface-analysis").style.pointerEvents="none";
    map.createPane("surface-lines");map.getPane("surface-lines").style.zIndex=410;map.getPane("surface-lines").style.pointerEvents="none";
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,pane:"surface-lines",attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(map);
    markers=L.layerGroup().addTo(map);lines=L.layerGroup().addTo(map);vectors=L.layerGroup().addTo(map);
    map.on("moveend",scheduleRender);
    map.on("click",event=>{
      if(!lastResult||mode()==="plots")return;
      const r=lastResult,x=Math.round((event.latlng.lng-r.bounds[0][1])/(r.bounds[1][1]-r.bounds[0][1])*(r.width-1));
      const y=Math.round((C.mercator(event.latlng.lat)-C.mercator(r.bounds[1][0]))/(C.mercator(r.bounds[0][0])-C.mercator(r.bounds[1][0]))*(r.height-1));
      if(x<0||y<0||x>=r.width||y>=r.height)return;
      const i=y*r.width+x,value=r.values[i];if(!Number.isFinite(value))return;
      const content=node("div");content.append(node("strong","Interpolated estimate"),node("p",`${C.fields[r.field].name}: ${value.toFixed(1)} ${C.fields[r.field].unit}`),node("p",`${r.support[i]} nearby stations · ${clock.format(new Date(data.hour))}`));
      if(r.field==="windMph"&&value>=.5){const from=(Math.atan2(-r.u[i],-r.v[i])*180/Math.PI+360)%360;content.append(node("p",`Wind from ${directions[Math.round(from/45)%8]} · arrows point where air moves`));}
      L.popup().setLatLng(event.latlng).setContent(content).openOn(map);
    });
  }
  function reset(){map?.setView([44.925,-93.35],map.getSize().x<600?9:8.5);}
  function clear(){worker?.terminate();worker=null;jobId++;markers?.clearLayers();lines?.clearLayers();vectors?.clearLayers();if(image){map.removeLayer(image);image=null;}lastResult=null;}
  function arrow(direction,x=30,y=24){
    return `<g transform="translate(${x} ${y}) rotate(${(direction+180)%360})" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M0 9V-9M-3 -4L0 -9L3 -4" stroke="white" stroke-width="4.5"/><path d="M0 9V-9M-3 -4L0 -9L3 -4" stroke="#111" stroke-width="1.7"/></g>`;
  }
  function popup(s){
    const box=node("div",null,"cloud-popup");box.append(node("strong",`${s.station} · ${s.name}`),node("p",`${s.network} · ${clock.format(new Date(s.time))}`));
    for(const key of ["tempF","dewpointF","rh","windMph","gustMph"]){
      const q=s.qc?.[key],value=s[key],label=C.fields[key];
      const desc=qcNames[q?.descriptor]||q?.descriptor||"Unavailable";
      const shown=Number.isFinite(value)?`${value.toFixed(1)} ${label.unit}`:"Not usable / not reported";
      box.append(node("p",`${label.name}: ${shown} · ${desc}${s.derived?.includes(key)?" · derived":""}${Number.isFinite(value)&&!C.allowed(s,key,quality())?" · excluded by selected quality filter":""}`));
    }
    if(Number.isFinite(s.direction))box.append(node("p",`Wind from ${directions[Math.round(s.direction/45)%8]} (${Math.round(s.direction)}°); arrow points toward destination.`));
    return box;
  }
  function visiblePlots(stations,field){
    const preferred=["KFCM","KMIC","KMSP"],rank=s=>preferred.includes(s.station)?preferred.indexOf(s.station):s.kind==="airport"?3:s.kind==="road"?4:5;
    const chosen=[],boxes=[],size=map.getSize();
    for(const s of [...stations].sort((a,b)=>rank(a)-rank(b)||a.id.localeCompare(b.id))){
      const point=map.latLngToContainerPoint([s.lat,s.lon]);if(point.x<0||point.y<0||point.x>size.x||point.y>size.y)continue;
      const plots=field==="plots",digits=plots?Math.max(rounded(s.tempF).length,rounded(s.dewpointF).length):rounded(s[field]).length;
      const box={left:point.x-(plots?12+digits*7:digits*4+5),right:point.x+(plots?14+rounded(s.windMph).length*7:digits*4+5),top:point.y-(plots?19:10),bottom:point.y+(plots?16:10)};
      if(boxes.some(b=>box.left<b.right&&box.right>b.left&&box.top<b.bottom&&box.bottom>b.top))continue;
      boxes.push(box);chosen.push(s);
    }
    return chosen;
  }
  function drawStations(stations,field){
    if(field!=="plots"&&!el("surface-stations").checked)return 0;
    const available=stations.filter(s=>field==="plots"?true:Number.isFinite(s[field])&&C.allowed(s,field,quality()));
    const chosen=visiblePlots(available,field);
    for(const s of chosen){
      let html,size,anchor;
      if(field==="plots"){
        const t=C.allowed(s,"tempF",quality())?s.tempF:null,d=C.allowed(s,"dewpointF",quality())?s.dewpointF:null,speed=C.allowed(s,"windMph",quality())?s.windMph:null;
        const glyph=speed!=null&&speed>=.5&&Number.isFinite(s.direction)&&C.allowed(s,"direction",quality())?arrow(s.direction):`<text class="plot-wind-state" x="30" y="27" text-anchor="middle">${speed==null?"?":speed<.5?"Calm":s.variable?"VRB":"?"}</text>`;
        html=`<svg class="metar-plot" width="67.2" height="35.2" viewBox="0 0 84 44" aria-hidden="true">${glyph}<text class="plot-temp" x="17" y="16" text-anchor="end">${rounded(t)}</text><text class="plot-dew" x="17" y="37" text-anchor="end">${rounded(d)}</text><text class="plot-speed" x="44" y="29">${rounded(speed)}</text></svg>`;
        size=[67.2,35.2];anchor=[24,19.2];
      }else{html=`<span class="surface-reading">${rounded(s[field])}</span>`;size=[30,22];anchor=[15,11];}
      L.marker([s.lat,s.lon],{icon:L.divIcon({className:"weather-station",html,iconSize:size,iconAnchor:anchor}),title:`${s.station} · ${s.network}`,keyboard:true}).bindPopup(popup(s)).addTo(markers);
    }
    return chosen.length;
  }
  function legend(){
    const field=mode(),parent=el("surface-legend");parent.replaceChildren();
    if(field==="plots"){parent.append(node("p","Temperature in red · dew point in green · °F. Black arrows point where wind goes; speed is mph. Airport plots have first priority.","small-note"));return;}
    const f=C.fields[field],ramp=C.palette(field,el("surface-colors").value),bar=node("div",null,"surface-gradient");
    bar.style.background=`linear-gradient(to right,${ramp.map(([n,c])=>`${c} ${(n-f.min)/(f.max-f.min)*100}%`).join(",")})`;
    const ticks=node("div",null,"reflectivity-ticks");for(const value of f.ticks)ticks.append(node("span",String(value)));
    parent.append(node("p",`${f.name} · ${f.unit} · fixed scale${["tempF","dewpointF"].includes(field)?" shared by temperature and dew point":""}`,"small-note"),bar,ticks);
  }
  function controls(){
    if(!manifest)return;
    const h=manifest.history,frame=h[frameIndex],slider=el("surface-timeline");
    slider.max=String(h.length-1);slider.value=String(frameIndex);slider.disabled=h.length<2;
    slider.style.setProperty("--progress",`${100*frameIndex/Math.max(1,h.length-1)}%`);
    el("surface-time").textContent=`${clock.format(new Date(frame.hour))} · ${frameIndex+1}/${h.length}`;
    slider.setAttribute("aria-valuetext",el("surface-time").textContent);
    el("surface-heading").textContent=C.fields[mode()].name;
    el("surface-style").disabled=mode()==="plots";el("surface-detail").disabled=mode()==="plots";
    el("surface-colors").disabled=mode()==="plots";el("surface-stations").disabled=mode()==="plots";
    legend();
  }
  function inventory(stations){
    const parent=el("surface-networks");parent.replaceChildren();const counts=new Map();
    for(const s of stations)counts.set(s.network,(counts.get(s.network)||0)+1);
    for(const [network,count] of [...counts].sort((a,b)=>b[1]-a[1]))parent.append(node("span",`${network}: ${count}`,"surface-network"));
    el("surface-rows").replaceChildren();if(!el("surface-list").open)return;
    const q=el("surface-search").value.trim().toUpperCase();
    for(const s of stations){
      if(q&&!`${s.station} ${s.name} ${s.network}`.toUpperCase().includes(q))continue;
      const row=node("tr"),td=node("td"),button=node("button",s.station,"station-link");button.addEventListener("click",()=>{map.setView([s.lat,s.lon],10);L.popup().setLatLng([s.lat,s.lon]).setContent(popup(s)).openOn(map);});td.append(button);
      const shown=key=>C.allowed(s,key,quality())?rounded(s[key]):"—";
      row.append(td,node("td",s.network),node("td",clock.format(new Date(s.time))),node("td",`${shown("tempF")} / ${shown("dewpointF")}`),node("td",`${shown("windMph")} mph`));el("surface-rows").append(row);
    }
  }
  function status(stations,drawn,analysis){
    const errors=data.sourceErrors||[];
    el("surface-status").textContent=`${stations.length} usable sites · ${drawn} station labels visible${analysis?` · ${analysis.count} sites support this field · ${analysis.radius} km maximum search`:""}${manifest.stale?" · Background update delayed":""}${errors.length?" · "+errors.join("; "):""}`;
    el("surface-note").textContent=mode()==="plots"?"Hourly observations within the preceding 30 minutes. Routine airports retain their :53 selection. Tap a station for its exact time, source and quality checks.":"Shading and contours estimate conditions between stations. Blank areas lack support from at least three nearby stations. Arrows show wind flow; speed is calculated from the combined wind vector. Tap shading for an estimate or a station for its measured value.";
  }
  function paint(result,stations,drawn){
    if(result.id!==jobId)return;
    if(result.error){el("surface-status").textContent=`Analysis unavailable: ${result.error}. Station observations remain available.`;return;}
    lastResult=result;
    const style=el("surface-style").value,field=result.field;
    if(style!=="contours"){
      const canvas=document.createElement("canvas");canvas.width=result.width;canvas.height=result.height;
      const context=canvas.getContext("2d"),pixels=context.createImageData(result.width,result.height);
      for(let i=0;i<result.values.length;i++)if(Number.isFinite(result.values[i])){const color=C.color(result.values[i],field,el("surface-colors").value);pixels.data.set([...color,190],i*4);}
      context.putImageData(pixels,0,0);image=L.imageOverlay(canvas.toDataURL(),result.bounds,{pane:"surface-analysis",interactive:false}).addTo(map);
    }
    if(style!=="filled")for(const contour of result.contours){
      L.polyline(contour.segments,{color:"#304139",weight:.75,opacity:.55,interactive:false,pane:"surface-lines"}).addTo(lines);
      // A few unboxed labels keep line-only comparisons readable.
      if(contour.segments.length>10){const segment=contour.segments[Math.floor(contour.segments.length/2)];L.marker(segment[0],{icon:L.divIcon({className:"surface-contour-label",html:String(contour.level),iconSize:[30,18],iconAnchor:[15,9]}),interactive:false}).addTo(lines);}
    }
    if(field==="windMph"){
      const spacing=map.getSize().x<600?45:55,step=Math.max(4,Math.round(spacing/(map.getSize().x/result.width)));
      const south=C.mercator(result.bounds[0][0]),north=C.mercator(result.bounds[1][0]);
      for(let y=2;y<result.height;y+=step)for(let x=2;x<result.width;x+=step){
        const i=y*result.width+x,speed=result.values[i];if(!Number.isFinite(speed)||speed<.5)continue;
        const from=(Math.atan2(-result.u[i],-result.v[i])*180/Math.PI+360)%360;
        const lat=C.latitude(north+(south-north)*y/(result.height-1)),lon=result.bounds[0][1]+(result.bounds[1][1]-result.bounds[0][1])*x/(result.width-1);
        L.marker([lat,lon],{icon:L.divIcon({className:"weather-station",html:`<svg width="26" height="26" viewBox="0 0 26 26">${arrow(from,13,13)}</svg>`,iconSize:[26,26],iconAnchor:[13,13]}),interactive:false}).addTo(vectors);
      }
    }
    status(stations,drawn,result);
  }
  function render(){
    if(!data||el("surface").hidden)return;
    init();clear();controls();
    const stations=C.filter(data.stations,source(),quality());inventory(stations);
    const field=mode(),drawn=drawStations(stations,field);status(stations,drawn);
    if(field==="plots")return;
    el("surface-status").textContent="Preparing the observed analysis…";
    const b=map.getBounds(),bounds=[[Math.max(40,b.getSouth()),Math.max(-104.5,b.getWest())],[Math.min(49.5,b.getNorth()),Math.min(-84,b.getEast())]];
    if(bounds[0][0]>=bounds[1][0]||bounds[0][1]>=bounds[1][1]){status(stations,drawn,{count:0,radius:0});return;}
    const size=map.getSize(),width=Math.max(30,Math.min(180,Math.round(size.x/7))),height=Math.max(30,Math.min(120,Math.round(size.y/7)));
    worker=new Worker("/static/surface-worker.js");worker.onmessage=event=>paint(event.data,stations,drawn);
    worker.onerror=()=>{el("surface-status").textContent="Analysis could not be prepared. Station observations remain available.";};
    worker.postMessage({id:jobId,stations,field,quality:quality(),detail:el("surface-detail").value,bounds,width,height});
  }
  function scheduleRender(){clearTimeout(renderTimer);renderTimer=setTimeout(render,120);}
  async function loadFrame(){
    const id=++requestId;controls();clear();data=null;
    const frame=manifest.history[frameIndex];
    if(!frame.url){el("surface-status").textContent="No saved observations for this hour. History fills as hourly collections complete.";el("surface-networks").replaceChildren();el("surface-rows").replaceChildren();return;}
    el("surface-status").textContent="Loading saved surface observations…";
    try{
      let payload=payloads.get(frame.url);if(!payload){payload=await read(frame.url);payloads.set(frame.url,payload);while(payloads.size>12)payloads.delete(payloads.keys().next().value);}
      if(id!==requestId)return;if(payload.hour!==frame.hour||payload.version!==1)throw Error("Surface snapshot mismatch");
      data=payload;render();
    }catch(error){if(id===requestId)el("surface-status").textContent=error.message;}
  }
  async function load(){
    if(busy)return;busy=true;el("refresh-surface").disabled=true;
    try{
      const selected=manifest?.history[frameIndex]?.hour,follow=!manifest||frameIndex===manifest.history.length-1;
      const next=await read("/api/surface");if(!next.history?.length||next.version!==1)throw Error("Surface data is being prepared.");
      manifest=next;const restored=follow?-1:manifest.history.findIndex(f=>f.hour===selected);frameIndex=restored>=0?restored:manifest.history.length-1;
      init();await loadFrame();
      clearTimeout(retryTimer);
      const now=new Date(),due=new Date(now);due.setUTCMinutes(10,0,0);if(due>now)due.setUTCHours(due.getUTCHours()-1);
      if(waitUntil>Date.now()&&new Date(manifest.checkedAt)<due)retry();else waitUntil=0;
    }catch(error){el("surface-status").textContent=`${error.message}${data?" Previous observations retained.":""}`;retry();}
    finally{busy=false;el("refresh-surface").disabled=false;}
  }
  function retry(){clearTimeout(retryTimer);if(waitUntil>Date.now())retryTimer=setTimeout(()=>{if(!document.hidden&&!el("surface").hidden)load();},60000);}
  function schedule(){
    clearTimeout(refreshTimer);const now=new Date(),next=new Date(now);next.setUTCMinutes(10,30,0);if(next<=now)next.setUTCHours(next.getUTCHours()+1);
    refreshTimer=setTimeout(()=>{if(!document.hidden&&!el("surface").hidden){waitUntil=Date.now()+3*60000;load();}schedule();},next-now);
  }
  function select(id){
    if(id==="surface"){init();waitUntil=Date.now()+3*60000;setTimeout(()=>{map.invalidateSize();load();},0);schedule();}
    else{worker?.terminate();worker=null;jobId++;}
  }
  for(const id of ["surface-field","surface-source","surface-quality","surface-style","surface-detail","surface-colors","surface-stations"])el(id).addEventListener("change",scheduleRender);
  el("surface-timeline").addEventListener("input",event=>{frameIndex=Number(event.target.value);loadFrame();});
  el("refresh-surface").addEventListener("click",load);el("surface-reset").addEventListener("click",reset);
  el("surface-region").addEventListener("click",()=>map?.fitBounds(manifest?.bounds||[[40,-104.5],[49.5,-84]]));
  el("surface-list").addEventListener("toggle",()=>{if(data)inventory(C.filter(data.stations,source(),quality()));});
  el("surface-search").addEventListener("input",()=>{if(data)inventory(C.filter(data.stations,source(),quality()));});
  return {select};
})();
