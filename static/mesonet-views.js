"use strict";
// Individual approved Hennepin West sites; never blend neighboring readings.
window.WeatherMesonet = (() => {
  const el=id=>document.getElementById(id),url="/api/mesonet",model=window.WeatherStationModel;
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const active=new Map(),options={dot:true,mphBarbs:true};
  let map,markers,data,busy=false,error=null;
  const activeView=()=>!el("metar").hidden&&el("metar-product").value==="mesonet";
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
    if(!activeView())return;
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
    const newest=stations.length?Math.max(...stations.map(s=>Date.parse(s.time))):null;
    const age=newest===null?null:Math.max(0,Math.floor((now-newest)/60000));
    const sourceDelayed=stations.some(s=>now-Date.parse(s.time)>900000);
    const checkDelayed=data?.collectorDelayed||data?.checkedAt&&now-Date.parse(data.checkedAt)>360000;
    const status=error?" · Refresh failed":checkDelayed?" · Collection delayed":data?.stale?" · Feed error":sourceDelayed?" · Source delayed":data?._savedCopy?" · Saved":"";
    const readout=el("metar-time");
    readout.textContent=stations.length?`Newest ${clock.format(new Date(newest))} · ${age}m old · ${stations.length} stations · °F · mph${status}`:busy?"Loading Hennepin West…":error?"Reports unavailable · try Refresh":"No approved station reports in the past 60 minutes";
    readout.title=data?.checkedAt?`Feed checked ${clock.format(new Date(data.checkedAt))}. Each plot uses its actual observation time; source delivery may lag collection.`:"Waiting for a prepared station snapshot";

  }
  function adopt(next){
    if(next?.stationPolicy!=="west-metro-roster-v2"||next?.coverage!=="hennepin-west-no-dakota-v1"||!Array.isArray(next.stations))return;
    if(data&&(Date.parse(next.checkedAt)<Date.parse(data.checkedAt)||next._savedCopy&&!data._savedCopy))return;
    data=next;error=null;
    if(next.serverTime&&!next._savedCopy)window.WeatherSun?.sync(next.serverTime);
    render();
  }
  async function load(force=false){
    if(busy)return;busy=true;if(activeView())el("refresh-metar").disabled=true;
    try{adopt(await window.WeatherPrepared.read(url,{force}));}catch(e){error=e.message;}
    finally{busy=false;if(activeView())el("refresh-metar").disabled=false;render();}
  }
  window.WeatherPrepared.subscribe(url,adopt);
  function saveDefault(){
    if(!map)return;const center=map.getCenter(),button=el("metar-set-default");
    button.textContent=window.WeatherDefaultViews?.saveMetar?.("mesonet",[center.lat,center.lng],map.getZoom())?"Default saved":"Could not save";
    setTimeout(()=>{button.textContent="Set default";},2000);
  }
  function resize(){if(activeView())map?.invalidateSize({pan:false});}
  window.addEventListener("weather-layout-resize",resize);
  return {render,reset,saveDefault,resize,busy:()=>busy,refresh(force=false){render();resize();return load(force);}};
})();
