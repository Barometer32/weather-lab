"use strict";
// Four-hour METAR loop with a fixed station roster per map.
window.WeatherMetars = (() => {
  const el=id=>document.getElementById(id),model=window.WeatherStationModel;
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let map,markers,data,index=0,followLatest=true,moving=false,sites=[],mode="plots",wantedHour=null;
  const historyHours=4;
  const windPlotOptions={dot:true,mphBarbs:true};
  const rtmetarUrl="/api/rtmetar",isHigh=()=>mode==="rtmetar",viewGroup=m=>m==="rtmetar"?"rtmetar":"hourly";
  const metroAirport=s=>s.lat>=44.65&&s.lat<=45.30&&s.lon>=-93.80&&s.lon<=-92.70;
  const rapidPriority=["KFCM","KMIC","KMSP","KSTP"];
  const rapidRank=s=>{const rank=rapidPriority.indexOf(s.station);return rank>=0?rank:metroAirport(s)?rapidPriority.length:rapidPriority.length+1;};
  const views={};
  let busy=false,sourceData,high,highBusy=false,highError;
  const plotCaches={plots:new WeakMap(),clouds:new WeakMap(),rtmetar:new WeakMap()};
  const cloudAvailable=station=>["CLR","SKC","NSC","NCD","CAVOK","FEW","SCT","BKN","OVC","VV"].includes(model.skyCode(station))&&model.cloudPlotLabel(station)!=="?";
  const active=new Map();
  el("metar-product").value=mode;
  el("metar-eyebrow").textContent=isHigh()?"FIVE-MINUTE ASOS · °C · MPH":"AIRPORT METARS · UPPER MIDWEST";
  el("metar-history").hidden=isHigh();
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  function reset(){
    if(!map)return;
    const saved=window.WeatherDefaultViews?.savedMetar?.(mode);
    if(isHigh()&&!saved){
      map.fitBounds([[40.30,-104.20],[49.45,-86.65]],{padding:[22,22],animate:false});return;
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
      const f=mode==="clouds"?model.cloudFootprint(station):model.combinedFootprint(station,windPlotOptions),old=bySite.get(station.station);
      bySite.set(station.station,{station,f:old?{left:Math.min(old.f.left,f.left),right:Math.max(old.f.right,f.right),top:Math.min(old.f.top,f.top),bottom:Math.max(old.f.bottom,f.bottom)}:f});
    }
    const preferred=["KFCM","KMIC","KMSP"],rank=s=>{
      const i=preferred.indexOf(s.station);return i<0?preferred.length:i;
    };
    sites=[...bySite.values()].sort((a,b)=>rank(a.station)-rank(b.station)||a.station.station.localeCompare(b.station.station));
  }
  function visible(stations){
    const size=map.getSize(),point=s=>map.latLngToContainerPoint([s.lat,s.lon]);
    const gap=isHigh()?0:2;
    const boxes=[],keep=new Set();
    for(const {station,f} of sites){
      const p=point(station);if(p.x<0||p.y<0||p.x>size.x||p.y>size.y)continue;const box={left:p.x+f.left,right:p.x+f.right,top:p.y+f.top,bottom:p.y+f.bottom};
      if(boxes.some(b=>box.left<b.right+gap&&box.right>b.left-gap&&box.top<b.bottom+gap&&box.bottom>b.top-gap))continue;
      boxes.push(box);keep.add(station.station);
    }
    return stations.filter(s=>keep.has(s.station));
  }
  function render(){
    if(el("metar").hidden||moving)return;
    if(isHigh()){renderHigh();return;}
    if(!data){drawEmptyHourly();return;}
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
  function drawEmptyHourly(){
    if(map)draw([]);
    el("metar-time").textContent="Loading hourly METARs…";
  }
  function renderHigh(){
    init();
    const now=Date.now(),stations=(high?.stations||[]).filter(s=>{
      const t=Date.parse(s.time);return now-3600000<=t&&t<=now&&Number.isFinite(s.tempC)&&Number.isFinite(s.dewpointC);
    });
    const options={...windPlotOptions,celsius:true};
    sites=stations.map(station=>{
      const footprint=model.combinedFootprint(station,options),space=metroAirport(station)?0.50:0.72;
      // Reserve a smaller collision area, allowing labels/barbs to overlap a
      // little. Keep the actual plot size and airport coordinates unchanged.
      return {station,f:Object.fromEntries(Object.entries(footprint).map(([key,value])=>[key,value*space]))};
    }).sort((a,b)=>rapidRank(a.station)-rapidRank(b.station)||a.station.station.localeCompare(b.station.station));
    draw(visible(stations));
    const newest=stations.length?time.format(new Date(Math.max(...stations.map(s=>Date.parse(s.time))))):null;
    el("metar-time").textContent=newest?`Newest ${newest} · ${stations.length} airport${stations.length===1?"":"s"} · °C${high.stale||high.sourceDelayed||highError||high._savedCopy?" · Delayed":""}`:
      highBusy?"Loading five-minute ASOS…":highError?"ASOS reports unavailable · try Refresh":"No five-minute reports with temperature and dewpoint in the past 60 minutes";
    el("metar-status").textContent=highError||(high?.checkedAt?`Checked ${time.format(new Date(high.checkedAt))} · 60-minute expiry`:"Upper Midwest five-minute ASOS");
    el("metar-map").setAttribute("aria-label","Five-minute reports from South Dakota, North Dakota, Minnesota, Iowa and Wisconsin; temperature and dewpoint in whole Celsius, wind barbs in mph");
  }
  function adoptHigh(next){
    if(next?.version!=="rtmetar-raw-c-v1"||next?.temperatureUnit!=="C"||!Array.isArray(next.stations)||next===high||high&&Date.parse(next.checkedAt)<Date.parse(high.checkedAt)||next._savedCopy&&high&&!high._savedCopy)return;
    high=next;highError=null;
    if(isHigh()){
      if(next.serverTime&&!next._savedCopy)window.WeatherSun?.sync(next.serverTime);
      render();
    }
  }
  async function loadHigh(force){
    if(highBusy)return;
    highBusy=true;el("refresh-metar").disabled=true;
    render();
    try{adoptHigh(await window.WeatherPrepared.read(rtmetarUrl,{force}));}
    catch(error){highError=error.message;}
    finally{
      highBusy=false;
      if(isHigh()){el("refresh-metar").disabled=false;render();}
    }
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
      const plot=mode==="clouds"?model.singleStationModel(station,"clouds"):model.combinedStationModel(station,{...windPlotOptions,celsius:isHigh()}),popup=node("div");popup.className="cloud-popup";
      popup.append(node("strong",isHigh()&&station.name?`${station.station} · ${station.name}`:station.station),node("p",station.time?time.format(new Date(station.time)):"Report time unavailable"));
      const temperatures=isHigh()?[station.tempC,station.dewpointC]:[station.tempF,station.dewpointF];
      for(const [i,label] of ["Temperature","Dewpoint"].entries()){
        const value=temperatures[i],display=Number.isFinite(value)?(isHigh()?`${value}°C`:`${value.toFixed(1)}°F`):"unavailable";
        popup.append(node("p",`${label}: ${display}`));
      }
      if(isHigh()){
        popup.append(node("p",`${station.state} · five-minute report`));
        if(station.rawOb)popup.append(node("p",station.rawOb));
      }
      const wind=station.wind||{},barb=model.combinedWind(wind,mode!=="clouds"&&windPlotOptions.mphBarbs),layer=model.firstCloudLayer(station);
      popup.append(node("p",`Wind: ${Number.isFinite(barb.speed)?Math.round(barb.speed)+" mph":"unknown"}${Number.isFinite(wind.direction)?" from "+Math.round(wind.direction)+"°":wind.variable?" · variable direction":""}`));
      if(!isHigh()){
        popup.append(node("p",`Cloud cover: ${model.skyCode(station)||"unavailable"}`));
        popup.append(node("p",layer?`${layer.cover}: ${layer.baseFtAGL.toLocaleString()} ft AGL`:model.cloudPlotLabel(station)==="?"?"Cloud report or ceiling height unavailable":"No BKN/OVC layer reported"));
      }
      if(barb.kind==="barb"){
        const feathers=mode==="clouds"?`${barb.roundedKnots} kt (nearest 5 kt)`:`${barb.roundedMph} mph`;
        popup.append(node("p",`Barb feathers: ${feathers}`));
      }
      const icon=L.divIcon({className:"weather-station",html:plot.html,iconSize:plot.size,iconAnchor:plot.anchor});
      cached={icon,popup};plots.set(station,cached);
      }
      if(existing){existing.marker.setIcon(cached.icon).setLatLng([station.lat,station.lon]).setPopupContent(cached.popup);existing.station=station;existing.mode=mode;}
      else {const marker=L.marker([station.lat,station.lon],{icon:cached.icon,title:`${station.station} · ${isHigh()?"RTMETAR":"METAR"}`,keyboard:true}).bindPopup(cached.popup).addTo(markers);active.set(station.station,{marker,station,mode});}
    }
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
    if(!isHigh())prepareSpacing();
    const restored=!followLatest&&selected?data.history.findIndex(f=>f.hour===selected):-1;
    index=restored>=0?restored:followLatest?data.history.length-1:0;
    if(!isHigh()){
      if(data.serverTime&&!data._savedCopy)window.WeatherSun?.sync(data.serverTime);
      render();
    }
  }
  async function load(force=false){
    if(isHigh())return loadHigh(force);
    if(busy)return;busy=true;el("refresh-metar").disabled=true;
    try{adopt(await window.WeatherPrepared.read("/api/station-plots?view=loop",{force}));}
    catch(error){if(!isHigh()){
      const message=`${error.message}${data?" Previous reports retained.":""}`;
      el("metar-status").textContent=message;
      if(!data)el("metar-time").textContent="Hourly history recovering…";
    }}
    finally{busy=false;if(!isHigh())el("refresh-metar").disabled=false;}
  }
  window.WeatherPrepared.subscribe("/api/station-plots?view=loop",adopt);
  window.WeatherPrepared.subscribe(rtmetarUrl,adoptHigh);
  function selectProduct(product){
    const previous=mode;
    const next=["plots","clouds","rtmetar"].includes(product)?product:"plots";
    const changedGroup=viewGroup(previous)!==viewGroup(next);
    if(map&&changedGroup){
      const center=map.getCenter();
      views[viewGroup(previous)]={center:[center.lat,center.lng],zoom:map.getZoom()};
      draw([]);
    }
    mode=next;
    el("metar-product").value=mode;
    el("metar-history").hidden=isHigh();
    el("metar-eyebrow").textContent=isHigh()?"FIVE-MINUTE ASOS · °C · MPH":"AIRPORT METARS · UPPER MIDWEST";
    el("refresh-metar").disabled=isHigh()?highBusy:busy;
    if(!isHigh()&&data)prepareSpacing();
    if(map&&(changedGroup||window.WeatherDefaultViews?.savedMetar?.(mode))){
      const view=!window.WeatherDefaultViews?.savedMetar?.(mode)&&views[viewGroup(mode)];
      if(view)map.setView(view.center,view.zoom,{animate:false});else reset();
    }
    if(!isHigh()&&!data)el("metar-time").textContent="Loading hourly METARs…";
    render();
    load();
  }
  el("metar-product").addEventListener("change",event=>selectProduct(event.target.value));
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
  setInterval(()=>{if(!document.hidden&&!el("metar").hidden)load();},30000);
  window.addEventListener("weather-layout-resize",()=>{if(map&&!el("metar").hidden)map.invalidateSize({pan:false});});
  return {select(id){if(id==="metar"){
    if(mode!=="plots")selectProduct("plots");else {render();load();}
    setTimeout(()=>map?.invalidateSize({pan:false}),0);
  }},refresh(){render();load();}};
})();
