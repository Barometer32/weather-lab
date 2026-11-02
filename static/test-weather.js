"use strict";
window.WeatherTest = (() => {
  const el=id=>document.getElementById(`test-${id}`);
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  let active=false,loaded=false,pending=false,map,pin,dots,serial=0,zone="UTC",last=0,point={latitude:44.797,longitude:-93.527,label:"Shakopee, MN"};
  try {const saved=JSON.parse(localStorage.getItem("weather-test-location"));if(saved&&Number.isFinite(saved.latitude)&&Number.isFinite(saved.longitude)&&Math.abs(saved.latitude)<=85&&Math.abs(saved.longitude)<=180)point=saved;}catch(_){}
  let historyData,liveData,historyIndex=12,followLatest=true;
  function date(value){if(!value)return "—";return new Intl.DateTimeFormat("en-US",{timeZone:zone,month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"}).format(new Date(value));}
  function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
  function clearConditions(){for(const id of ["temp","dew","wind"])el(id).textContent="—";el("valid").textContent="Loading observations…";el("checked").textContent="";el("warning").hidden=true;el("support").replaceChildren();el("support-title").textContent="Station support and method";dots?.clearLayers();}
  async function read(path,signal){const response=await fetch(path,{signal,cache:"no-store"});let data;try{data=await response.json();}catch(_){throw new Error("Weather service did not return data. Please retry.");}if(!response.ok)throw new Error(data.error||"Weather request failed.");return data;}
  function initMap(){
    if(map)return;
    map=L.map("test-map",{minZoom:3,maxZoom:15,zoomSnap:.5,zoomDelta:.5}).setView([point.latitude,point.longitude],10);
    for(const [layer,opacity] of [["uscounties",.4],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${layer}/{z}/{x}/{y}.png`,{opacity,attribution:'Boundaries: <a href="https://mesonet.agron.iastate.edu/ogc/">Iowa Environmental Mesonet</a>'}).addTo(map);
    dots=L.layerGroup().addTo(map);
    pin=L.circleMarker([point.latitude,point.longitude],{radius:7,color:"#fff",weight:2,fillColor:"#15834f",fillOpacity:1}).addTo(map);
    map.on("click",event=>{point={latitude:Number(event.latlng.lat.toFixed(4)),longitude:Number(event.latlng.lng.toFixed(4)),label:`${event.latlng.lat.toFixed(4)}, ${event.latlng.lng.toFixed(4)}`};load(true);});
  }
  function renderConditions(data){
    const f=data.fields||{},value=name=>f[name]?.value;
    el("temp").textContent=value("temperatureF")==null?"—":`${Math.round(value("temperatureF"))}°F`;
    el("dew").textContent=value("dewpointF")==null?"—":`${Math.round(value("dewpointF"))}°F`;
    const speed=value("windMph");el("wind").textContent=speed==null?"—":speed<.5?"0":`${directions[Math.round(data.windDirection/45)%8]} ${Math.round(speed)}`;
    el("valid").textContent=data.observationStart?`Reports ${date(data.observationStart)} – ${date(data.observationEnd)}`:data.message||"No recent nearby reports.";
    el("checked").textContent=`Station cache checked ${date(data.checkedAt)} · ${data.stationCount||0} supporting sites · ${data.gridSpacingKm} km analysis grid`;
    const warnings=[data.message,data.stale?"Background station checks are delayed. Observation times above are unchanged.":"",data.sourceErrors?.length?"Some public feeds could not be refreshed; available recent reports are used.":"",data.available&&Object.values(f).some(x=>x.value==null)?"Some values have insufficient station support.":""] .filter(Boolean);
    el("warning").textContent=warnings.join(" ");el("warning").hidden=!warnings.length;
    el("support-title").textContent=`Station support and method · ${data.stationCount||0} sites`;
    const support=el("support");support.replaceChildren();
    if(data.pendingFiles?.length)support.append(node("p","NOAA has not published some current-hour files yet; recent reports from the preceding file are still eligible."));
    for(const [name,label] of [["temperatureF","Temperature"],["dewpointF","Dewpoint"],["windMph","Wind"]]){const field=f[name];if(field?.value!=null)support.append(node("p",`${label}: ${field.stationCount} stations · representative observation ${date(field.representativeTime)} · nearest ${field.nearestKm} km`));}
    if(data.stations?.length){
      const wrap=node("div",null,"test-support-table"),table=node("table"),head=node("thead"),hr=node("tr");for(const name of ["Site / network","Report time","Distance"])hr.append(node("th",name));head.append(hr);table.append(head);const body=node("tbody");
      for(const row of data.stations){const tr=node("tr");tr.append(node("td",`${row.station} · ${row.network||row.provider||row.source}`),node("td",date(row.time)),node("td",`${row.distanceKm} km`));body.append(tr);L.circleMarker([row.lat,row.lon],{radius:3,color:"#68766d",weight:1,fillOpacity:.7}).bindPopup(node("span",`${row.station} · ${row.name||row.network} · ${date(row.time)}`)).addTo(dots);}
      table.append(body);wrap.append(table);support.append(wrap);
    }
  }
  function historyField(frame,name){return frame?.fields?.[name]?.value;}
  function drawHistory(){
    const host=el("chart");host.replaceChildren();if(!historyData?.frames?.length)return;
    const ns="http://www.w3.org/2000/svg",svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox","0 0 520 178");svg.setAttribute("role","img");svg.setAttribute("aria-label","Past 12 hours: red temperature and green dewpoint in degrees Fahrenheit; gray wind speed in miles per hour. Gaps are missing observations.");
    function shape(tag,attrs,text){const n=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attrs))n.setAttribute(key,String(value));if(text!=null)n.textContent=text;svg.append(n);return n;}
    const frames=historyData.frames,x=i=>36+i*474/Math.max(1,frames.length-1);
    const values=frames.flatMap(f=>[historyField(f,"temperatureF"),historyField(f,"dewpointF")]).filter(v=>v!=null);
    let low=values.length?Math.floor((Math.min(...values)-2)/5)*5:0,high=values.length?Math.ceil((Math.max(...values)+2)/5)*5:10;
    if(high-low<10){low-=5;high+=5;}const y=v=>98-(v-low)/(high-low)*74;
    for(const value of [low,(low+high)/2,high]){shape("line",{x1:36,y1:y(value),x2:510,y2:y(value),stroke:"#e5ebe7"});shape("text",{x:30,y:y(value)+3,"text-anchor":"end",fill:"#66756c","font-size":10},`${Math.round(value)}°`);}
    function line(name,color,project){let path="",pen=false;frames.forEach((frame,i)=>{const value=historyField(frame,name);if(value==null){pen=false;return;}path+=`${pen?"L":"M"}${x(i).toFixed(1)},${project(value).toFixed(1)} `;pen=true;});shape("path",{d:path,fill:"none",stroke:color,"stroke-width":2,"stroke-linejoin":"round"});}
    line("temperatureF","#b92126",y);line("dewpointF","#16804a",y);
    const windValues=frames.map(f=>historyField(f,"windMph")).filter(v=>v!=null),windMax=Math.max(10,Math.ceil(Math.max(0,...windValues)/5)*5),wy=v=>151-v/windMax*30;
    shape("text",{x:36,y:116,fill:"#66756c","font-size":10},`Wind · 0–${windMax} mph`);line("windMph","#67746d",wy);
    shape("line",{x1:x(historyIndex),y1:20,x2:x(historyIndex),y2:153,stroke:"#17834f","stroke-width":1,"stroke-dasharray":"3 3"});
    const timeFormat=new Intl.DateTimeFormat("en-US",{timeZone:zone,hour:"numeric",minute:"2-digit"});
    for(const i of [0,Math.floor((frames.length-1)/2),frames.length-1])shape("text",{x:x(i),y:170,"text-anchor":i===0?"start":i===frames.length-1?"end":"middle",fill:"#66756c","font-size":10},i===frames.length-1?"Current":timeFormat.format(new Date(frames[i].time)));
    shape("text",{x:36,y:12,fill:"#b92126","font-size":10},"Temperature °F");shape("text",{x:143,y:12,fill:"#16804a","font-size":10},"Dewpoint °F");host.append(svg);
  }
  function showHistory(index){
    if(!historyData?.frames?.length){if(liveData)renderConditions(liveData);return;}
    historyIndex=Math.max(0,Math.min(Number(index),historyData.frames.length-1));followLatest=historyIndex===historyData.frames.length-1;
    const frame=followLatest&&liveData?liveData:historyData.frames[historyIndex];dots?.clearLayers();renderConditions(frame);
    const label=followLatest?"Current conditions":`Estimate for ${date(historyData.frames[historyIndex].time)}`;
    el("history-time").textContent=label;el("timeline").value=String(historyIndex);el("timeline").setAttribute("aria-valuetext",label);el("timeline").style.setProperty("--progress",`${historyIndex/(historyData.frames.length-1)*100}%`);drawHistory();
  }
  function renderHistory(data){
    historyData=data;el("timeline").max=String(data.frames.length-1);el("timeline").disabled=false;
    const gaps=data.frames.filter(f=>!f.available).length;
    el("history-status").textContent=`Hourly samples at this location · each uses its preceding 30 minutes${gaps?` · ${gaps} samples have insufficient data`:""}${data.archiveReadErrors?" · Some archives could not load":""}`;
    showHistory(followLatest?data.frames.length-1:historyIndex);
  }
  function renderForecast(data){
    zone=data.timeZone||"America/Chicago";
    el("issued").textContent=`NWS issued ${date(data.updatedAt)}${data.location?` · ${data.location}`:""}`;
    el("nws-link").href=data.sourceUrl;
    el("periods").replaceChildren();
    for(const p of data.periods){const a=node("article",null,"test-period"),h=node("h3");h.append(node("span",p.name),node("strong",p.temperature==null?"—":`${p.temperature}°${p.temperatureUnit||"F"}`));a.append(h,node("p",p.detailedForecast));el("periods").append(a);}
  }
  async function load(moved=false){
    if(!active)return;initMap();zone="UTC";const request=++serial;last=Date.now();loaded=true;pending=true;
    el("location").textContent=point.label;el("place").value=point.label;
    if(moved)map.setView([point.latitude,point.longitude],Math.max(9,map.getZoom()));pin.setLatLng([point.latitude,point.longitude]);
    try{localStorage.setItem("weather-test-location",JSON.stringify(point));}catch(_){}
    if(moved){historyData=undefined;historyIndex=12;followLatest=true;el("chart").replaceChildren();el("timeline").disabled=true;el("history-time").textContent="Current conditions";}
    liveData=undefined;clearConditions();el("history-status").textContent="Loading twelve-hour history…";el("periods").replaceChildren();el("issued").textContent="Loading NWS forecast…";el("status").textContent="Checking selected point…";
    el("nws-link").href=`https://forecast.weather.gov/MapClick.php?lat=${point.latitude}&lon=${point.longitude}`;
    const query=new URLSearchParams({lat:point.latitude,lon:point.longitude,minutes:30});
    let conditions,forecast;
    const results=await Promise.allSettled([
      read(`/api/test/conditions?${query}`).then(data=>{if(request!==serial)return;conditions=data;liveData=data;if(followLatest||!historyData)renderConditions(data);}),
      read(`/api/test/forecast?${query}`).then(data=>{if(request!==serial)return;forecast=data;renderForecast(data);}),
      read(`/api/test/history?${query}`).then(data=>{if(request!==serial)return;renderHistory(data);})
    ]);
    if(request!==serial)return;pending=false;
    // Re-render the times after the point's NWS time zone becomes available.
    if(conditions){if(historyData)showHistory(followLatest?historyData.frames.length-1:historyIndex);else{dots.clearLayers();renderConditions(conditions);}}
    if(results[0].status==="rejected")el("valid").textContent=results[0].reason.message;
    if(results[1].status==="rejected")el("issued").textContent=results[1].reason.message;
    if(results[2].status==="rejected")el("history-status").textContent=results[2].reason.message;
    el("status").textContent=conditions?.available?"Estimated conditions at the selected pin.":"Current estimate is unavailable; no sufficiently recent station support for this point.";
  }
  el("search").addEventListener("submit",async event=>{event.preventDefault();const query=el("place").value,request=++serial;el("status").textContent="Finding location…";try{const found=await read(`/api/test/location?${new URLSearchParams({q:query})}`);if(request!==serial)return;point=found;load(true);}catch(error){if(request===serial)el("status").textContent=error.message;}});
  el("locate").addEventListener("click",()=>{if(!navigator.geolocation){el("status").textContent="Location is unavailable. Enter a place or coordinates.";return;}const request=++serial;el("status").textContent="Waiting for your location permission…";navigator.geolocation.getCurrentPosition(position=>{if(request!==serial)return;point={latitude:Number(position.coords.latitude.toFixed(4)),longitude:Number(position.coords.longitude.toFixed(4)),label:"Your location"};load(true);},()=>{if(request===serial)el("status").textContent="Location was not available. Enter a city or tap the map.";},{timeout:15000,maximumAge:60000});});
  el("timeline").addEventListener("input",event=>showHistory(event.target.value));el("live").addEventListener("click",()=>{followLatest=true;showHistory(historyData?.frames?.length-1||12);});
  el("refresh").addEventListener("click",()=>load());
  setInterval(()=>{if(active&&!document.hidden&&Date.now()-last>=300000)load();},30000);
  window.addEventListener("weather-layout-resize",()=>{if(active)map?.invalidateSize();});
  return {select(id){active=id==="test";if(active){initMap();setTimeout(()=>map.invalidateSize(),0);if(!loaded||Date.now()-last>=300000)load();}else {serial++;if(pending)loaded=false;pending=false;}}};
})();
