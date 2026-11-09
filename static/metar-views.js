"use strict";
// Four-hour METAR loop with a fixed station roster per map.
window.WeatherMetars = (() => {
  const el=id=>document.getElementById(id),model=window.WeatherStationModel;
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let map,markers,data,index=0,followLatest=true,moving=false,sites=[],mode=el("metar-product").value||"plots",wantedHour=null;
  const historyHours=4;
  let busy=false,sourceData;
  const mesonetUrl="/api/observation-stations?view=mesonet";
  let mesonet,mesonetBusy=false,mesonetError,mesonetFitted=false;
  let mesonetRoads;
  const views={};
  const viewGroup=product=>product==="mesonet"?"mesonet":"airports";
  const plotCaches={plots:new WeakMap(),clouds:new WeakMap(),mesonet:new WeakMap()};
  const cloudAvailable=station=>["CLR","SKC","NSC","NCD","CAVOK","FEW","SCT","BKN","OVC","VV"].includes(model.skyCode(station))&&model.cloudPlotLabel(station)!=="?";
  const active=new Map();
  el("metar-product").value=mode;
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  function showProduct(){
    const local=mode==="mesonet";
    el("metar-history").hidden=local;
    el("metar-eyebrow").textContent=local?"HENNEPIN WEST MESONET":"AIRPORT METARS · UPPER MIDWEST";
  }
  showProduct();
  function reset(){
    if(!map)return;
    const saved=window.WeatherDefaultViews?.savedMetar?.(mode);
    if(mode==="mesonet"&&!saved){
      const points=mesonet?.stations.map(s=>[s.lat,s.lon])||[];
      map.fitBounds(points.length>1?points:mesonet?.bounds||[[44.78,-93.78],[45.25,-93.18]],{padding:[42,42],maxZoom:12,animate:false});
      return;
    }
    const view=saved||window.WeatherDefaultViews?.metar(sites,map.getSize())||{center:[44.945,-93.343],zoom:9};
    map.setView(view.center,view.zoom,{animate:false});
  }
  function init(){
    if(map)return;
    map=L.map("metar-map",{minZoom:5,maxZoom:13,zoomSnap:.25,zoomDelta:.25,wheelPxPerZoomLevel:90});reset();
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(map);
    markers=L.layerGroup().addTo(map);
    map.on("movestart",()=>{moving=true;});
    map.on("moveend",()=>{moving=false;render();});
    syncRoads();
  }
  function syncRoads(){
    if(!map)return;
    if(mode!=="mesonet"){mesonetRoads?.remove();return;}
    if(mesonetRoads)mesonetRoads.addTo(map);
    else mesonetRoads=window.WeatherRadarRoads?.addTo(map,undefined,{primaryOnly:true});
  }
  function readyWindow(history){
    // Stage partial arrivals outside the viewer. A new batch must retain at
    // least 90% of airports present in each of the previous three hours.
    for(let end=history.length;end>=historyHours;end--){
      const frames=history.slice(end-historyHours,end);
      if(frames.some((f,i)=>!f.stations?.length||!Number.isFinite(Date.parse(f.hour))||
          (i>0&&Date.parse(f.hour)-Date.parse(frames[i-1].hour)!==3600000)))continue;
      const sets=frames.map(f=>new Set(f.stations.map(s=>s.station)));
      const expected=[...sets[0]].filter(id=>sets[1].has(id)&&sets[2].has(id));
      if(expected.length>=20&&expected.filter(id=>sets[3].has(id)).length/expected.length<.90)continue;
      if(["KFCM","KMIC","KMSP"].some(id=>expected.includes(id)&&!sets[3].has(id)))continue;
      return frames;
    }
    return null;
  }
  function prepareSpacing(){
    // Eligibility is computed separately for PLOTS and CLOUDS, before overlap
    // checks. An airport missing any frame must not displace a steady neighbor.
    const reports=data.history.map(frame=>frame.stations.filter(station=>mode!=="clouds"||cloudAvailable(station)));
    const eligible=new Set(reports[0].map(station=>station.station));
    for(const stations of reports.slice(1)){
      const present=new Set(stations.map(station=>station.station));
      for(const id of eligible)if(!present.has(id))eligible.delete(id);
    }
    // Reserve the largest label across all four frames to avoid flickering
    // station density as the user moves the timeline.
    const bySite=new Map();
    for(const stations of reports)for(const station of stations){
      if(!eligible.has(station.station))continue;
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
    return stations.filter(s=>keep.has(s.station));
  }
  function render(){
    if(el("metar").hidden||moving)return;
    if(mode==="mesonet"){renderMesonet();return;}
    if(!data)return;
    init();
    const hours=data.history;
    if(followLatest){const last=hours.findLastIndex(f=>f.stations.length);index=last<0?hours.length-1:last;}
    index=Math.max(0,Math.min(index,hours.length-1));
    const frame=hours[index];
    draw(visible(frame.stations));
    const slider=el("metar-timeline");slider.max=String(hours.length-1);slider.value=String(index);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*index/(hours.length-1):0}%`);
    el("metar-time").textContent=`${data._savedCopy?"Saved · ":""}${time.format(new Date(frame.hour))} · ${index+1}/${hours.length}`;
    slider.setAttribute("aria-valuetext",el("metar-time").textContent);
    el("metar-map").setAttribute("aria-label",mode==="clouds"?"Airport sky-cover circles with the lowest BKN or OVC height to the right, in thousands of feet AGL":"Hourly airport temperature, dewpoint and wind barbs with state and county boundaries");
    el("metar-status").textContent=`${sites.length} airports with data in all four hours${data.stale?" · Background updates delayed":""}`;
  }
  function draw(drawn){
    const keep=new Set(drawn.map(s=>s.station));
    for(const [id,entry] of active)if(!keep.has(id)){markers.removeLayer(entry.marker);active.delete(id);}
    for(const station of drawn){
      const existing=active.get(station.station);
      if(existing?.station===station&&existing.mode===mode)continue;
      const plots=plotCaches[mode];
      let cached=plots.get(station);
      if(!cached){
      const plot=mode==="clouds"?model.singleStationModel(station,"clouds"):model.combinedStationModel(station,{dot:true,mphBarbs:mode==="mesonet"}),popup=node("div");popup.className="cloud-popup";
      popup.append(node("strong",mode==="mesonet"&&station.displayName?`${station.displayName} (${station.station})`:station.station),node("p",station.time?time.format(new Date(station.time)):"Report time unavailable"));
      for(const [label,value] of [["Temperature",station.tempF],["Dewpoint",station.dewpointF]])popup.append(node("p",`${label}: ${Number.isFinite(value)?value.toFixed(1)+"°F":"unavailable"}`));
      const wind=station.wind||{},barb=model.combinedWind(wind,mode==="mesonet"),layer=model.firstCloudLayer(station);
      popup.append(node("p",`Wind: ${Number.isFinite(barb.speed)?Math.round(barb.speed)+" mph":"unknown"}${Number.isFinite(wind.direction)?" from "+Math.round(wind.direction)+"°":wind.variable?" · variable direction":""}`));
      if(mode!=="mesonet"){
        popup.append(node("p",`Cloud cover: ${model.skyCode(station)||"unavailable"}`));
        popup.append(node("p",layer?`${layer.cover}: ${layer.baseFtAGL.toLocaleString()} ft AGL`:model.cloudPlotLabel(station)==="?"?"Cloud report or ceiling height unavailable":"No BKN/OVC layer reported"));
      }
      if(barb.kind==="barb"){
        if(mode==="mesonet"&&barb.roundedMph>0)popup.append(node("p",`Barb feathers: ${barb.roundedMph} mph`));
        else if(barb.roundedKnots>0)popup.append(node("p",`Barb feathers: ${barb.roundedKnots} kt (nearest 5 kt)`));
      }
      const icon=L.divIcon({className:"weather-station",html:plot.html,iconSize:plot.size,iconAnchor:plot.anchor});
      cached={icon,popup};plots.set(station,cached);
      }
      if(existing){existing.marker.setIcon(cached.icon).setLatLng([station.lat,station.lon]).setPopupContent(cached.popup);existing.station=station;existing.mode=mode;}
      else {const marker=L.marker([station.lat,station.lon],{icon:cached.icon,title:`${station.station} · ${mode==="mesonet"?"MESONET":"METAR"}`,keyboard:true}).bindPopup(cached.popup).addTo(markers);active.set(station.station,{marker,station,mode});}
    }
  }
  function renderMesonet(){
    init();
    const stations=(mesonet?.stations||[]).filter(s=>Date.now()-Date.parse(s.time)<=3600000);
    if(!mesonetFitted&&stations.length){mesonetFitted=true;reset();}
    // Keep every reporting network site available even when labels are close.
    draw(stations);
    const newest=Math.max(...stations.map(s=>Date.parse(s.time)));
    const delayed=mesonetError||mesonet?.stale||mesonet?._savedCopy||Date.now()-newest>1200000;
    el("metar-time").textContent=stations.length?`Newest: ${time.format(new Date(newest))}${delayed?" · Delayed":""}`
      :mesonetBusy?"Loading Mesonet readings…":"No recent Mesonet readings";
    el("metar-status").textContent=mesonetError||`${stations.length} Hennepin West stations · checked every 5 minutes`;
    el("metar-map").setAttribute("aria-label","Hennepin West Mesonet temperature, dewpoint and wind barbs");
  }
  function adoptMesonet(next){
    if(!Array.isArray(next?.stations)||next===mesonet||next._savedCopy&&mesonet&&!mesonet._savedCopy)return;
    mesonet=next;mesonetError=null;
    if(mode==="mesonet"){
      if(next.serverTime&&!next._savedCopy)window.WeatherSun?.sync(next.serverTime);
      render();
    }
  }
  async function loadMesonet(force=false){
    if(mesonetBusy)return;
    mesonetBusy=true;el("refresh-metar").disabled=true;
    render();
    try{adoptMesonet(await window.WeatherPrepared.read(mesonetUrl,{force}));}
    catch(error){mesonetError=error.message;}
    finally{mesonetBusy=false;if(mode==="mesonet"){el("refresh-metar").disabled=false;render();}}
  }
  function adopt(next){
    if(!next.history?.length)throw Error("Hourly reports are not ready");
    if(sourceData===next)return;
    if(next._savedCopy&&data&&!data._savedCopy&&next.checkedAt<=data.checkedAt)return;
    // Older saved copies in the browser can still include the excluded airport.
    const history=readyWindow(next.history.map(frame=>({...frame,stations:frame.stations?.filter(s=>s.station!=="KCFE")})));
    if(!history){
      if(data){el("metar-status").textContent="Waiting for a complete hourly batch; previous reports retained.";return;}
      throw Error("Four consecutive populated airport hours are not ready");
    }
    // Out-of-order responses or a deteriorating feed must not roll the
    // timeline backwards after a newer usable window has been displayed.
    if(data&&Date.parse(history.at(-1).hour)<Date.parse(data.history.at(-1).hour))return;
    const selected=data?.history[index]?.hour||wantedHour;
    sourceData=next;data={...next,history};
    if(mode!=="mesonet")prepareSpacing();
    const restored=!followLatest&&selected?data.history.findIndex(f=>f.hour===selected):-1;
    index=restored>=0?restored:followLatest?data.history.length-1:0;
    if(mode!=="mesonet"){
      if(data.serverTime&&!data._savedCopy)window.WeatherSun?.sync(data.serverTime);
      render();
    }
  }
  async function load(force=false){
    if(mode==="mesonet")return loadMesonet(force);
    if(busy)return;busy=true;el("refresh-metar").disabled=true;
    try{adopt(await window.WeatherPrepared.read("/api/station-plots?view=loop",{force}));}
    catch(error){if(mode!=="mesonet"){el("metar-status").textContent=`${error.message}${data?" Previous reports retained.":""}`;if(!data)el("metar-time").textContent="Reports unavailable · try Refresh";}}
    finally{busy=false;if(mode!=="mesonet")el("refresh-metar").disabled=false;}
  }
  window.WeatherPrepared.subscribe("/api/station-plots?view=loop",adopt);
  window.WeatherPrepared.subscribe(mesonetUrl,adoptMesonet);
  el("metar-product").addEventListener("change",event=>{
    const previous=mode;
    const next=["plots","clouds","mesonet"].includes(event.target.value)?event.target.value:"plots";
    const changedGroup=viewGroup(previous)!==viewGroup(next);
    if(map&&changedGroup){
      const center=map.getCenter();views[viewGroup(previous)]={center:[center.lat,center.lng],zoom:map.getZoom()};
      draw([]);
    }
    if(previous!=="mesonet")wantedHour=data?.history[index]?.hour||wantedHour;
    mode=next;
    el("metar-product").value=mode;
    showProduct();
    if(changedGroup)syncRoads();
    el("refresh-metar").disabled=mode==="mesonet"?mesonetBusy:busy;
    if(mode!=="mesonet"&&data)prepareSpacing();
    if(map&&(changedGroup||window.WeatherDefaultViews?.savedMetar?.(mode))){
      const view=changedGroup&&!window.WeatherDefaultViews?.savedMetar?.(mode)&&views[viewGroup(mode)];
      if(view)map.setView(view.center,view.zoom,{animate:false});else reset();
    }
    if(mode!=="mesonet"&&!data)el("metar-time").textContent="Loading hourly METARs…";
    render();
    load();
  });
  el("refresh-metar").addEventListener("click",()=>load(true));
  el("metar-reset").addEventListener("click",reset);
  el("metar-set-default").addEventListener("click",()=>{
    if(!map)return;
    const center=map.getCenter(),button=el("metar-set-default");
    const saved=window.WeatherDefaultViews?.saveMetar?.(mode,[center.lat,center.lng],map.getZoom());
    button.textContent=saved?"Default saved":"Could not save";
    setTimeout(()=>{button.textContent="Set default";},2000);
  });
  el("metar-timeline").addEventListener("input",event=>{if(!data)return;index=Number(event.target.value);wantedHour=data.history[index]?.hour;followLatest=index===data.history.length-1;render();});
  window.WeatherFullscreen.attach({surfaceId:"metar-surface",buttonId:"metar-fullscreen",label:"METAR map",onResize:()=>{if(map){map.invalidateSize({pan:false});render();}}});
  setInterval(()=>{if(mode!=="mesonet"&&!document.hidden&&!el("metar").hidden)load();},30000);
  setInterval(()=>{if(mode==="mesonet"&&!document.hidden&&!el("metar").hidden)load();},300000);
  window.addEventListener("weather-layout-resize",()=>{if(map&&!el("metar").hidden)map.invalidateSize({pan:false});});
  return {select(id){if(id==="metar"){render();load();setTimeout(()=>map?.invalidateSize({pan:false}),0);}}};
})();
