"use strict";
// Prepared estimates only: no MADIS downloads or interpolation in the browser.
window.WeatherExpmet=(()=>{
  const el=id=>document.getElementById(id),model=window.WeatherStationModel;
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let map,layer,data,busy=false,moving=false,mode="all";const active=new Map();
  const savedKey="weather-expmet-view-v1";
  function saved(){try{const v=JSON.parse(window.localStorage?.getItem(savedKey)||"null");if(Array.isArray(v?.center)&&v.center.length===2&&v.center.every(Number.isFinite)&&v.center[0]>=40&&v.center[0]<=50&&v.center[1]>=-100&&v.center[1]<=-85&&Number.isFinite(v.zoom)&&v.zoom>=5&&v.zoom<=13)return v;}catch(_){}return null;}
  function reset(){if(map){const v=saved()||window.WeatherDefaultViews?.savedMetar?.("plots")||{center:[44.95,-93.4],zoom:8.5};map.setView(v.center,v.zoom,{animate:false});}}
  function init(){
    if(map)return;
    map=L.map("expmet-map",{minZoom:5,maxZoom:13,zoomSnap:.25,zoomDelta:.25,wheelPxPerZoomLevel:90});reset();
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:'Boundaries: Iowa Environmental Mesonet · Estimates: NOAA MADIS + airport METARs'}).addTo(map);
    layer=L.layerGroup().addTo(map);
    map.on("movestart",()=>{moving=true;});map.on("moveend",()=>{moving=false;render();});
  }
  function stride(){
    // Keep an anchored regular subgrid rather than moving estimates to airports.
    const origin=map.latLngToContainerPoint([45,-93]),east=map.latLngToContainerPoint([45,-93+data.gridKm/(111.195*Math.cos(Math.PI/4))]),north=map.latLngToContainerPoint([45+data.gridKm/111.195,-93]);
    const spacing=Math.min(Math.abs(east.x-origin.x),Math.abs(north.y-origin.y));
    let step=1;while(step<128&&step*spacing<85)step*=2;return step;
  }
  const valid=s=>mode==="temperature"?Number.isFinite(s.tempF):mode==="dewpoint"?Number.isFinite(s.dewpointF):mode==="wind"?Number.isFinite(s.wind?.speedMph):true;
  function plot(s){
    if(mode==="temperature"||mode==="dewpoint")return model.singleStationModel(s,mode);
    const p=model.combinedStationModel(s,{dot:true});
    if(mode==="wind")p.html=p.html.replace(/<text class="plot-(?:temp|dew)"[^>]*>.*?<\/text>/g,"");
    return p;
  }
  function popup(s){
    const box=document.createElement("div"),line=text=>{const p=document.createElement("p");p.textContent=text;box.append(p);};
    line("Experimental grid estimate");line(`${s.lat.toFixed(3)}°, ${s.lon.toFixed(3)}° · ${time.format(new Date(data.analysisTime))}`);
    for(const [label,value] of [["Temperature",s.tempF],["Dewpoint",s.dewpointF]])line(`${label}: ${Number.isFinite(value)?value.toFixed(1)+"°F":"insufficient support"}`);
    const w=s.wind||{};line(`Wind: ${Number.isFinite(w.speedMph)?Math.round(w.speedMph)+" mph":"insufficient support"}${Number.isFinite(w.direction)?" from "+Math.round(w.direction)+"°":""}`);
    for(const [field,n] of Object.entries(s.support||{}))line(`${field}: ${s.contributors?.[field]??n} contributing sites · nearest ${s.nearestKm[field]} km · weighted report age ${s.ageMinutes[field]} min${s.extrapolated?.[field]?" · sparse coverage, distant-station estimate":""}`);
    line("Estimated from observations available at collection time. No terrain correction or forecast model.");
    return box;
  }
  function render(){
    if(!data||el("expmet").hidden||moving)return;init();
    const step=stride(),size=map.getSize(),keep=new Set();
    for(const s of data.stations){
      if(s.gx%step||s.gy%step||!valid(s))continue;
      const point=map.latLngToContainerPoint([s.lat,s.lon]);if(point.x<0||point.y<0||point.x>size.x||point.y>size.y)continue;
      keep.add(s.station);const old=active.get(s.station);
      if(old?.row===s&&old.mode===mode)continue;
      const p=plot(s),icon=L.divIcon({className:"weather-station",html:p.html,iconSize:p.size,iconAnchor:p.anchor}),content=popup(s);
      if(old){old.marker.setIcon(icon).setPopupContent(content);old.row=s;old.mode=mode;}
      else{const marker=L.marker([s.lat,s.lon],{icon,title:"Estimated grid point",keyboard:true}).bindPopup(content).addTo(layer);active.set(s.station,{marker,row:s,mode});}
    }
    for(const [id,entry] of active)if(!keep.has(id)){layer.removeLayer(entry.marker);active.delete(id);}
    el("expmet-time").textContent=`${data._savedCopy?"Saved · ":""}Analysis ${time.format(new Date(data.analysisTime))}${data.stale?" · delayed":""}`;
    const airports=data.providers?.["Airport METAR"]||0;
    el("expmet-status").textContent=`Estimated · ${airports} airports + ${data.stationCount-airports} public MADIS sites · ${data.gridKm} km grid${!data.sources?.madis?" · MADIS unavailable":""}${!data.sources?.airports?" · airport feed unavailable":""}${data.stale?" · collection delayed":""}`;
  }
  function adopt(next){if(!next.stations?.length)throw Error("No supported analysis points yet");if(next._savedCopy&&data&&!data._savedCopy&&next.checkedAt<=data.checkedAt)return;data=next;render();}
  async function load(force=false){if(busy)return;busy=true;el("refresh-expmet").disabled=true;try{adopt(await window.WeatherPrepared.read("/api/expmet",{force}));}catch(error){el("expmet-status").textContent=error.message+(data?" Previous analysis retained.":"");}finally{busy=false;el("refresh-expmet").disabled=false;}}
  el("refresh-expmet").addEventListener("click",()=>load(true));
  el("expmet-product").addEventListener("change",event=>{mode=["all","temperature","dewpoint","wind"].includes(event.target.value)?event.target.value:"all";render();});
  el("expmet-reset").addEventListener("click",reset);
  el("expmet-set-default").addEventListener("click",()=>{if(!map)return;const c=map.getCenter();try{window.localStorage.setItem(savedKey,JSON.stringify({center:[c.lat,c.lng],zoom:map.getZoom()}));el("expmet-set-default").textContent="Default saved";}catch(_){el("expmet-set-default").textContent="Could not save";}setTimeout(()=>{el("expmet-set-default").textContent="Set default";},2000);});
  window.WeatherPrepared.subscribe("/api/expmet",adopt);
  window.WeatherFullscreen.attach({surfaceId:"expmet-surface",buttonId:"expmet-fullscreen",label:"experimental analysis",onResize:()=>{if(map){map.invalidateSize({pan:false});render();}}});
  window.addEventListener("weather-layout-resize",()=>{if(map&&!el("expmet").hidden)map.invalidateSize({pan:false});});
  setInterval(()=>{if(!document.hidden&&!el("expmet").hidden)load();},60000);
  return {select(id){if(id==="expmet"){render();load();setTimeout(()=>map?.invalidateSize({pan:false}),0);}}};
})();
