"use strict";
// Individual approved Hennepin West sites; never blend neighboring readings.
window.WeatherMesonet = (() => {
  const el=id=>document.getElementById(id),url="/api/mesonet",model=window.WeatherStationModel;
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const active=new Map(),options={dot:true,mphBarbs:true};
  let map,markers,data,busy=false,error=null;
  const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
  function reset(){
    if(!map)return;
    const saved=window.WeatherDefaultViews?.savedMetar?.("mesonet");
    if(saved)map.setView(saved.center,saved.zoom,{animate:false});
    else map.fitBounds(data?.bounds||[[44.70,-94.00],[45.35,-92.95]],{padding:[40,40],animate:false,maxZoom:11});
  }
  function init(){
    if(map)return;
    map=L.map("mesonet-map",{minZoom:5,maxZoom:13,zoomSnap:.25,zoomDelta:.25,wheelPxPerZoomLevel:90});
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(map);
    markers=L.layerGroup().addTo(map);reset();
  }
  function render(){
    if(el("mesonet").hidden)return;
    init();
    const now=Date.now(),stations=(data?.stations||[]).filter(s=>s.network==="Hennepin West"&&/^HPN\d+$/.test(s.station)&&Number.isFinite(s.lat)&&Number.isFinite(s.lon)&&Date.parse(s.time)<=now&&Date.parse(s.time)>=now-3600000);
    const keep=new Set(stations.map(s=>s.station));
    for(const [id,entry] of active)if(!keep.has(id)){markers.removeLayer(entry.marker);active.delete(id);}
    for(const station of stations){
      if(active.get(station.station)?.station===station)continue;
      const plot=model.combinedStationModel(station,options),popup=node("div","");popup.className="cloud-popup";
      popup.append(node("strong",`${station.displayName} · ${station.station}`),node("p",clock.format(new Date(station.time))));
      for(const [label,value] of [["Temperature",station.tempF],["Dewpoint",station.dewpointF]])popup.append(node("p",`${label}: ${Number.isFinite(value)?value.toFixed(1)+"°F":"unavailable"}`));
      const wind=station.wind||{};
      popup.append(node("p",`Wind: ${Number.isFinite(wind.speedMph)?Math.round(wind.speedMph)+" mph":"unavailable"}${Number.isFinite(wind.direction)?" from "+Math.round(wind.direction)+"°":""}`),node("p","Hennepin West · NOAA MADIS"));
      const icon=L.divIcon({className:"weather-station",html:plot.html,iconSize:plot.size,iconAnchor:plot.anchor}),old=active.get(station.station);
      if(old){old.marker.setIcon(icon).setLatLng([station.lat,station.lon]).setPopupContent(popup);old.station=station;}
      else active.set(station.station,{station,marker:L.marker([station.lat,station.lon],{icon,title:`${station.displayName} · ${station.station}`,keyboard:true}).bindPopup(popup).addTo(markers)});
    }
    const delayed=error||data?.stale||data?._savedCopy||stations.some(s=>now-Date.parse(s.time)>900000);
    el("mesonet-time").textContent=stations.length?`Newest ${clock.format(new Date(Math.max(...stations.map(s=>Date.parse(s.time)))))} · ${stations.length} stations · °F · mph${delayed?" · Delayed":""}`:busy?"Loading Hennepin West…":error?"Reports unavailable · try Refresh":"No approved station reports in the past 60 minutes";
  }
  function adopt(next){
    if(next?.stationPolicy!=="west-metro-roster-v2"||next?.coverage!=="hennepin-west-no-dakota-v1"||!Array.isArray(next.stations))return;
    if(data&&(Date.parse(next.checkedAt)<Date.parse(data.checkedAt)||next._savedCopy&&!data._savedCopy))return;
    data=next;error=null;render();
  }
  async function load(force=false){
    if(busy)return;busy=true;el("refresh-mesonet").disabled=true;
    try{adopt(await window.WeatherPrepared.read(url,{force}));}catch(e){error=e.message;}
    finally{busy=false;el("refresh-mesonet").disabled=false;render();}
  }
  window.WeatherPrepared.subscribe(url,adopt);
  el("refresh-mesonet").addEventListener("click",()=>load(true));
  el("mesonet-reset").addEventListener("click",reset);
  el("mesonet-set-default").addEventListener("click",()=>{
    if(!map)return;const center=map.getCenter(),button=el("mesonet-set-default");
    button.textContent=window.WeatherDefaultViews?.saveMetar?.("mesonet",[center.lat,center.lng],map.getZoom())?"Default saved":"Could not save";
    setTimeout(()=>{button.textContent="Set default";},2000);
  });
  window.WeatherFullscreen.attach({surfaceId:"mesonet-surface",buttonId:"mesonet-fullscreen",label:"MESONET map",onResize:()=>map?.invalidateSize({pan:false})});
  window.addEventListener("weather-layout-resize",()=>{if(!el("mesonet").hidden)map?.invalidateSize({pan:false});});
  setInterval(()=>{if(!document.hidden&&!el("mesonet").hidden){render();load();}},30000);
  return {select(id){if(id==="mesonet"){render();load();setTimeout(()=>map?.invalidateSize({pan:false}),0);}},refresh(){render();load();}};
})();
