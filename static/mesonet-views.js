"use strict";
// Local approved Hennepin West plots, separate from the hourly airport loop.
window.WeatherMesonet=(()=>{
  const el=id=>document.getElementById(id),endpoint="/api/mesonet",model=window.WeatherStationModel;
  const focus=[[44.78,-93.65],[45.19,-93.07]],panBounds=[[44.65,-93.85],[45.32,-92.9]];
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  const options={mesonet:true,dot:true,mphBarbs:true};
  let map,layer,data,active=false,busy=false;const markers=new Map();
  const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
  const validView=view=>view&&view.zoom>=8.5&&view.zoom<=13&&view.center[0]>=panBounds[0][0]&&view.center[0]<=panBounds[1][0]&&view.center[1]>=panBounds[0][1]&&view.center[1]<=panBounds[1][1];
  function reset(){
    if(!map)return;
    const saved=window.WeatherDefaultViews?.savedMetar("mesonet");
    if(validView(saved))map.setView(saved.center,saved.zoom,{animate:false});
    else map.fitBounds(focus,{padding:[32,40],maxZoom:11,animate:false});
  }
  function init(){
    if(map)return;
    map=L.map("mesonet-map",{minZoom:8.5,maxZoom:13,zoomSnap:.25,zoomDelta:.25,wheelPxPerZoomLevel:90,maxBounds:panBounds,maxBoundsViscosity:1});
    reset();
    for(const [kind,opacity] of [["uscounties",.23],["usstates",.65]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(map);
    const roads=window.WeatherRadarRoads?.addTo(map,()=>{el("mesonet-map").setAttribute("data-highway-status","unavailable");},{primaryOnly:true});
    roads?.setOpacity(.23);
    layer=L.layerGroup().addTo(map);
  }
  function windText(w={}){
    if(!Number.isFinite(w.speedMph))return "Unavailable";
    if(w.speedMph<.5)return "Calm";
    return `${Number.isFinite(w.direction)?directions[Math.round(w.direction/45)%8]:"Variable"} ${Math.round(w.speedMph)} mph`;
  }
  function render(){
    if(!active||el("metar").hidden||!data)return;
    init();const rows=(data.stations||[]).filter(s=>Date.now()-Date.parse(s.time)<=86400000),keep=new Set(rows.map(s=>s.station));
    for(const [id,entry] of markers)if(!keep.has(id)){layer.removeLayer(entry);markers.delete(id);}
    // All approved available sites are retained. Zoom separates close plots;
    // changing wind direction never changes which stations are admitted.
    for(const station of rows){
      const plot=model.combinedStationModel(station,options),popup=node("div","");popup.className="cloud-popup";
      popup.append(node("strong",`${station.displayName||station.station} · ${station.station}`),node("p",`Observed ${time.format(new Date(station.time))}`));
      const age=Math.max(0,Math.floor((Date.now()-Date.parse(station.time))/60000));
      popup.append(node("p",`${age} minutes old`));
      for(const [label,value] of [["Temperature",station.tempF],["Dewpoint",station.dewpointF]])popup.append(node("p",`${label}: ${Number.isFinite(value)?value.toFixed(1)+"°F":"Unavailable"}`));
      popup.append(node("p",`Wind: ${windText(station.wind)}`));
      const icon=L.divIcon({className:"weather-station",html:plot.html,iconSize:plot.size,iconAnchor:plot.anchor});
      const old=markers.get(station.station);
      if(old)old.setIcon(icon).setLatLng([station.lat,station.lon]).setPopupContent(popup);
      else markers.set(station.station,L.marker([station.lat,station.lon],{icon,title:`${station.displayName||station.station} · ${station.station} · ${time.format(new Date(station.time))}`,keyboard:true}).bindPopup(popup).addTo(layer));
    }
    const newestAge=Math.max(0,Math.floor((Date.now()-Date.parse(data.newestObservationAt))/60000));
    el("mesonet-time").textContent=rows.length?`Newest ${time.format(new Date(data.newestObservationAt))} · ${newestAge} min old · ${rows.length} stations · °F · mph${newestAge>15||data.sourceDelayed?" · Source delayed":""}${data._savedCopy?" · Saved":""}${data.collectorDelayed?" · Collector delayed":""}`:"No Hennepin West reports available in the last 24 hours";
    el("mesonet-map").setAttribute("aria-label","Approved local Hennepin West Mesonet temperature, dewpoint and mph wind plots with faint major highways");
  }
  function adopt(next){
    if(!Array.isArray(next.stations))throw Error("Hennepin West observations are not ready");
    if(data&&next.checkedAt<data.checkedAt)return;
    data=next;render();
  }
  async function load(force=false){
    if(busy)return;busy=true;if(active)el("refresh-metar").disabled=true;
    try{adopt(await window.WeatherPrepared.read(endpoint,{force}));}
    catch(error){if(!data)el("mesonet-time").textContent=error.message;else el("mesonet-time").textContent+=" · Refresh unavailable";}
    finally{busy=false;if(active)el("refresh-metar").disabled=false;}
  }
  el("mesonet-reset").addEventListener("click",reset);
  el("mesonet-set-default").addEventListener("click",()=>{
    if(!map)return;const c=map.getCenter(),button=el("mesonet-set-default");
    button.textContent=window.WeatherDefaultViews?.saveMetar("mesonet",[c.lat,c.lng],map.getZoom())?"Default saved":"Could not save";
    setTimeout(()=>{button.textContent="Set default";},2000);
  });
  window.WeatherFullscreen.attach({surfaceId:"mesonet-surface",buttonId:"mesonet-fullscreen",label:"Hennepin West Mesonet",onResize:()=>map?.invalidateSize({pan:false})});
  window.WeatherPrepared.subscribe(endpoint,adopt);
  setInterval(()=>{if(active&&!document.hidden)load(true);},300000);
  setInterval(()=>{if(active&&!document.hidden)render();},60000);
  document.addEventListener("visibilitychange",()=>{if(active&&!document.hidden)load(true);});
  window.addEventListener("weather-layout-resize",()=>{if(active)map?.invalidateSize({pan:false});});
  return {load,select(mode){active=mode==="mesonet";if(active){init();render();load();setTimeout(()=>map.invalidateSize({pan:false}),0);}}};
})();
