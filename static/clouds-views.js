"use strict";
// Current hour plus the preceding three hours, with complete station history.
window.WeatherClouds = (() => {
  const el=id=>document.getElementById(id),model=window.WeatherStationModel;
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let map,markers,data,index=0,followLatest=true,moving=false,sites=[],mode="clouds",wantedHour=null;
  const historyHours=4;
  let busy=false,sourceData;
  let suppressed=new Set();
  const plotCaches={plots:new WeakMap(),clouds:new WeakMap()};
  const eligible=station=>mode!=="clouds"||Boolean(model.cloudHeightText(station));
  const active=new Map();
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  function reset(){
    if(!map)return;
    const view=window.WeatherDefaultViews?.savedMetar?.(mode)||window.WeatherDefaultViews?.metar(sites,map.getSize())||{center:[44.945,-93.343],zoom:9};
    map.setView(view.center,view.zoom,{animate:false});
  }
  function init(){
    if(map)return;
    map=L.map("clouds-map",{minZoom:5,maxZoom:13,zoomSnap:.25,zoomDelta:.25,wheelPxPerZoomLevel:90});reset();
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(map);
    markers=L.layerGroup().addTo(map);
    map.on("movestart",()=>{moving=true;});
    map.on("moveend",()=>{moving=false;render();});
  }
  function incompleteSites(history){
    // A report must exist in each of the four displayed frames. Leading,
    // trailing and whole-frame gaps count; cloud changes and spacing do not.
    const presence=history.map(frame=>new Set(frame.stations.map(station=>station.station)));
    const ids=new Set(history.flatMap(frame=>frame.stations.map(station=>station.station)));
    return new Set([...ids].filter(id=>history.length!==historyHours||presence.some(frame=>!frame.has(id))));
  }
  function prepareSpacing(){
    // Reserve the largest label across all four frames to avoid flickering
    // station density as the user moves the timeline.
    const bySite=new Map();
    for(const frame of data.history)for(const station of frame.stations){
      if(suppressed.has(station.station)||!eligible(station))continue;
      const f=mode==="clouds"?model.cloudFootprint(station):model.combinedFootprint(station,{dot:true}),old=bySite.get(station.station);
      bySite.set(station.station,{station,f:old?{left:Math.min(old.f.left,f.left),right:Math.max(old.f.right,f.right),top:Math.min(old.f.top,f.top),bottom:Math.max(old.f.bottom,f.bottom)}:f});
    }
    const preferred=["KFCM","KMIC","KMSP"],rank=s=>{
      const i=preferred.indexOf(s.station);return i<0?preferred.length:i;
    };
    sites=[...bySite.values()].sort((a,b)=>rank(a.station)-rank(b.station)||a.station.station.localeCompare(b.station.station));
  }
  function visible(stations){
    const size=map.getSize(),point=s=>map.latLngToContainerPoint([s.lat,s.lon]);
    const boxes=[],keep=new Set();
    for(const {station,f} of sites){
      const p=point(station);if(p.x<0||p.y<0||p.x>size.x||p.y>size.y)continue;const box={left:p.x+f.left,right:p.x+f.right,top:p.y+f.top,bottom:p.y+f.bottom};
      if(boxes.some(b=>box.left<b.right+2&&box.right>b.left-2&&box.top<b.bottom+2&&box.bottom>b.top-2))continue;
      boxes.push(box);keep.add(station.station);
    }
    return stations.filter(s=>keep.has(s.station)&&eligible(s));
  }
  function render(){
    if(!data||el("clouds").hidden||moving)return;
    init();
    const hours=data.history;
    if(followLatest){const last=hours.findLastIndex(f=>f.stations.length);index=last<0?hours.length-1:last;}
    index=Math.max(0,Math.min(index,hours.length-1));
    const frame=hours[index],drawn=visible(frame.stations);
    const keep=new Set(drawn.map(s=>s.station));
    for(const [id,entry] of active)if(!keep.has(id)){markers.removeLayer(entry.marker);active.delete(id);}
    for(const station of drawn){
      const existing=active.get(station.station);
      if(existing?.station===station&&existing.mode===mode)continue;
      const plots=plotCaches[mode];
      let cached=plots.get(station);
      if(!cached){
      const plot=mode==="clouds"?model.singleStationModel(station,"clouds"):model.combinedStationModel(station,{dot:true}),popup=node("div");popup.className="cloud-popup";
      popup.append(node("strong",station.station),node("p",station.time?time.format(new Date(station.time)):"Report time unavailable"));
      const layer=model.firstCloudLayer(station);
      popup.append(node("p",layer?`${layer.cover}: ${layer.baseFtAGL.toLocaleString()} ft AGL`:"No known BKN/OVC ceiling"));
      const icon=L.divIcon({className:"weather-station",html:plot.html,iconSize:plot.size,iconAnchor:plot.anchor});
      cached={icon,popup};plots.set(station,cached);
      }
      if(existing){existing.marker.setIcon(cached.icon).setLatLng([station.lat,station.lon]).setPopupContent(cached.popup);existing.station=station;existing.mode=mode;}
      else {const marker=L.marker([station.lat,station.lon],{icon:cached.icon,title:`${station.station} · airport ceiling`,keyboard:true}).bindPopup(cached.popup).addTo(markers);active.set(station.station,{marker,station,mode});}
    }
    const slider=el("clouds-timeline");slider.max=String(hours.length-1);slider.value=String(index);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*index/(hours.length-1):0}%`);
    el("clouds-time").textContent=`${data._savedCopy?"Saved · ":""}${time.format(new Date(frame.hour))} · ${index+1}/${hours.length}`;
    slider.setAttribute("aria-valuetext",el("clouds-time").textContent);
    el("clouds-map").setAttribute("aria-label",mode==="clouds"?"Lowest BKN or OVC airport cloud heights in thousands of feet":"Lowest airport ceiling");
    el("clouds-status").textContent=`${frame.stations.length} airport reports${!hours.at(-1).stations.length?" · Waiting for the newest hour":""}${data.stale?" · Background updates delayed":""}`;
  }
  function adopt(next){
    if(!next.history?.length)throw Error("Hourly reports are not ready");
    if(sourceData===next)return;
    if(next._savedCopy&&data&&!data._savedCopy&&next.checkedAt<=data.checkedAt)return;
    const selected=data?.history[index]?.hour||wantedHour;
    sourceData=next;data={...next,history:next.history.slice(-historyHours)};
    suppressed=incompleteSites(data.history);prepareSpacing();
    const restored=!followLatest&&selected?data.history.findIndex(f=>f.hour===selected):-1;
    index=restored>=0?restored:followLatest?data.history.length-1:0;
    if(data.serverTime&&!data._savedCopy)window.WeatherSun?.sync(data.serverTime);
    render();
  }
  async function load(force=false){
    if(busy)return;busy=true;el("clouds-refresh").disabled=true;
    try{adopt(await window.WeatherPrepared.read("/api/clouds",{force}));}
    catch(error){el("clouds-status").textContent=`${error.message}${data?" Previous reports retained.":""}`;if(!data)el("clouds-time").textContent="Reports unavailable · try Refresh";}
    finally{busy=false;el("clouds-refresh").disabled=false;}
  }
  window.WeatherPrepared.subscribe("/api/clouds",adopt);
  el("clouds-refresh").addEventListener("click",()=>load(true));
  el("clouds-reset").addEventListener("click",reset);
  el("clouds-set-default").addEventListener("click",()=>{
    if(!map)return;
    const center=map.getCenter(),button=el("clouds-set-default");
    const saved=window.WeatherDefaultViews?.saveMetar?.(mode,[center.lat,center.lng],map.getZoom());
    button.textContent=saved?"Default saved":"Could not save";
    setTimeout(()=>{button.textContent="Set default";},2000);
  });
  el("clouds-timeline").addEventListener("input",event=>{if(!data)return;index=Number(event.target.value);wantedHour=data.history[index]?.hour;followLatest=index===data.history.length-1;render();});
  window.WeatherFullscreen.attach({surfaceId:"clouds-surface",buttonId:"clouds-fullscreen",label:"cloud height map",onResize:()=>{if(map){map.invalidateSize({pan:false});render();}}});
  setInterval(()=>{if(!document.hidden&&!el("clouds").hidden)load();},30000);
  window.addEventListener("weather-layout-resize",()=>{if(map&&!el("clouds").hidden)map.invalidateSize({pan:false});});
  return {select(id){if(id==="clouds"){render();load();setTimeout(()=>map?.invalidateSize({pan:false}),0);}}};
})();
