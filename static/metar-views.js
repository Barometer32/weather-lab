"use strict";
// One compact combined station model for each prepared hourly airport report.
window.WeatherMetars = (() => {
  const el=id=>document.getElementById(id),model=window.WeatherStationModel;
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let map,markers,data,index=0,followLatest=true,busy=false,moving=false,sites=[];
  const active=new Map(),plots=new WeakMap();
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  function reset(){
    if(!map)return;
    const view=window.WeatherDefaultViews?.metar(sites,map.getSize())||{center:[44.945,-93.343],zoom:9};
    map.setView(view.center,view.zoom,{animate:false});
  }
  function init(){
    if(map)return;
    map=L.map("metar-map",{minZoom:5,maxZoom:13,zoomSnap:.25,zoomDelta:.25,wheelPxPerZoomLevel:90});reset();
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(map);
    markers=L.layerGroup().addTo(map);
    map.on("movestart",()=>{moving=true;});
    map.on("moveend",()=>{moving=false;render();});
  }
  function prepareSpacing(){
    // Reserve the largest label across all twelve hours to avoid flickering
    // station density as the user moves the timeline.
    const bySite=new Map();
    for(const frame of data.history)for(const station of frame.stations){
      const f=model.combinedFootprint(station),old=bySite.get(station.station);
      bySite.set(station.station,{station,f:old?{left:Math.min(old.f.left,f.left),right:Math.max(old.f.right,f.right),top:Math.min(old.f.top,f.top),bottom:Math.max(old.f.bottom,f.bottom)}:f});
    }
    const preferred=["KFCM","KMIC","KMSP"],rank=s=>{const i=preferred.indexOf(s.station);return i<0?preferred.length:i;};
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
    return stations.filter(s=>keep.has(s.station));
  }
  function render(){
    if(!data||el("metar").hidden||moving)return;
    init();
    const hours=data.history;
    if(followLatest){const last=hours.findLastIndex(f=>f.stations.length);index=last<0?hours.length-1:last;}
    index=Math.max(0,Math.min(index,hours.length-1));
    const frame=hours[index],drawn=visible(frame.stations);
    const keep=new Set(drawn.map(s=>s.station));
    for(const [id,entry] of active)if(!keep.has(id)){markers.removeLayer(entry.marker);active.delete(id);}
    for(const station of drawn){
      const existing=active.get(station.station);
      if(existing?.station===station)continue;
      let cached=plots.get(station);
      if(!cached){
      const plot=model.combinedStationModel(station),popup=node("div");popup.className="cloud-popup";
      popup.append(node("strong",station.station),node("p",station.time?time.format(new Date(station.time)):"Report time unavailable"));
      for(const [label,value] of [["Temperature",station.tempF],["Dewpoint",station.dewpointF]])popup.append(node("p",`${label}: ${Number.isFinite(value)?value.toFixed(1)+"°F":"unavailable"}`));
      const wind=station.wind||{},barb=model.combinedWind(wind),layer=model.firstCloudLayer(station);
      popup.append(node("p",`Wind: ${Number.isFinite(barb.speed)?Math.round(barb.speed)+" mph":"unknown"}${Number.isFinite(wind.direction)?" from "+Math.round(wind.direction)+"°":wind.variable?" · variable direction":""}`));
      popup.append(node("p",`Cloud cover: ${model.skyCode(station)||"unavailable"}`));
      popup.append(node("p",layer?`${layer.cover}: ${layer.baseFtAGL.toLocaleString()} ft AGL`:model.cloudPlotLabel(station)==="?"?"Cloud report or ceiling height unavailable":"No BKN/OVC layer reported"));
      if(barb.kind==="barb")popup.append(node("p",`Barb feathers: ${barb.roundedKnots} kt (nearest 5 kt)`));
      const icon=L.divIcon({className:"weather-station",html:plot.html,iconSize:plot.size,iconAnchor:plot.anchor});
      cached={icon,popup};plots.set(station,cached);
      }
      if(existing){existing.marker.setIcon(cached.icon).setLatLng([station.lat,station.lon]).setPopupContent(cached.popup);existing.station=station;}
      else {const marker=L.marker([station.lat,station.lon],{icon:cached.icon,title:`${station.station} · METAR`,keyboard:true}).bindPopup(cached.popup).addTo(markers);active.set(station.station,{marker,station});}
    }
    const slider=el("metar-timeline");slider.max=String(hours.length-1);slider.value=String(index);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*index/(hours.length-1):0}%`);
    el("metar-time").textContent=`${data._savedCopy?"Saved · ":""}${time.format(new Date(frame.hour))} · ${index+1}/${hours.length}`;
    slider.setAttribute("aria-valuetext",el("metar-time").textContent);
    el("metar-map").setAttribute("aria-label","Hourly airport station models: temperature, dewpoint, cloud cover, ceiling and wind barbs with state and county boundaries");
    el("metar-status").textContent=`${frame.stations.length} airport reports${!hours.at(-1).stations.length?" · Waiting for the newest hour":""}${data.stale?" · Background updates delayed":""}`;
  }
  function adopt(next){
    if(!next.history?.length)throw Error("Hourly airport reports are not ready");
    if(data===next)return;
    if(next._savedCopy&&data&&!data._savedCopy&&next.checkedAt<=data.checkedAt)return;
    const selected=data?.history[index]?.hour;data=next;prepareSpacing();
    const restored=!followLatest&&selected?data.history.findIndex(f=>f.hour===selected):-1;
    index=restored>=0?restored:followLatest?data.history.length-1:0;
    if(data.serverTime&&!data._savedCopy)window.WeatherSun?.sync(data.serverTime);
    render();
  }
  async function load(force=false){
    if(busy)return;busy=true;el("refresh-metar").disabled=true;
    try{adopt(await window.WeatherPrepared.read("/api/station-plots",{force}));}
    catch(error){el("metar-status").textContent=`${error.message}${data?" Previous reports retained.":""}`;if(!data)el("metar-time").textContent="METAR reports unavailable · try Refresh";}
    finally{busy=false;el("refresh-metar").disabled=false;}
  }
  window.WeatherPrepared.subscribe("/api/station-plots",adopt);
  el("refresh-metar").addEventListener("click",()=>load(true));
  el("metar-reset").addEventListener("click",reset);
  el("metar-timeline").addEventListener("input",event=>{if(!data)return;index=Number(event.target.value);followLatest=index===data.history.length-1;render();});
  window.WeatherFullscreen.attach({surfaceId:"metar-surface",buttonId:"metar-fullscreen",label:"METAR map",onResize:()=>{if(map){map.invalidateSize({pan:false});render();}}});
  setInterval(()=>{if(!document.hidden&&!el("metar").hidden)load();},30000);
  window.addEventListener("weather-layout-resize",()=>{if(map&&!el("metar").hidden)map.invalidateSize({pan:false});});
  return {select(id){if(id==="metar"){render();load();setTimeout(()=>map?.invalidateSize({pan:false}),0);}}};
})();
