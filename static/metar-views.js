"use strict";
// Four-hour METAR loop with independent airport eligibility in each hour.
window.WeatherMetars = (() => {
  const el=id=>document.getElementById(id),model=window.WeatherStationModel,cityPlots=window.WeatherMetarPlots;
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const defaultProduct="plots";
  let map,markers,data,index=0,followLatest=true,moving=false,sites=[],mode=defaultProduct,wantedHour=null;
  const historyHours=4;
  const preferred=["KMSP","KFCM","KMIC"];
  const secondary=["KSTP"];
  const windPlotOptions={dot:true,mphBarbs:true};
  const windSpacingFactor=.90; // Small barb-to-number contact is acceptable.
  let busy=false,sourceData;
  const plotCaches={plots:new WeakMap(),clouds:new WeakMap()};
  const cloudAvailable=station=>["CLR","SKC","NSC","NCD","CAVOK","FEW","SCT","BKN","OVC","VV"].includes(model.skyCode(station))&&model.cloudPlotLabel(station)!=="?";
  const active=new Map();
  el("metar-product").value=mode;
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  function reset(){
    if(!map)return;
    const saved=window.WeatherDefaultViews?.savedMetar?.(mode);
    if(mode==="plots"&&!saved){
      map.fitBounds(cityPlots.locations,{padding:[32,32],animate:false});
      return;
    }
    const view=saved||window.WeatherDefaultViews?.metar(sites,map.getSize(),preferred)||{center:[44.945,-93.343],zoom:9};
    map.setView(view.center,view.zoom,{animate:false});
  }
  function init(){
    if(map)return;
    map=L.map("metar-map",{attributionControl:false,minZoom:5,maxZoom:13,zoomSnap:.25,zoomDelta:.25,wheelPxPerZoomLevel:90});reset();
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
      return frames;
    }
    return null;
  }
  function prepareSpacing(){
    // Index each hour independently. A missing report in one hour must not
    // remove the airport from another hour where it has usable data.
    const reports=mode==="plots"?data.plots:data.history.map(frame=>frame.stations.filter(cloudAvailable));
    const bySite=new Map();
    for(const [index,stations] of reports.entries())for(const station of stations){
      const old=bySite.get(station.station),frames=old?.frames||Array.from({length:data.history.length},()=>[]);
      const reservation=mode==="plots"?model.combinedReservation(station,windPlotOptions):null;
      const f=reservation?.bounds||model.cloudFootprint(station);
      frames[index]=reservation?.boxes||[f];
      bySite.set(station.station,{station,frames,radius:Math.max(old?.radius||0,reservation?.radius||0),
        f:old?{left:Math.min(old.f.left,f.left),right:Math.max(old.f.right,f.right),top:Math.min(old.f.top,f.top),bottom:Math.max(old.f.bottom,f.bottom)}:f});
    }
    const rank=s=>{
      const i=preferred.indexOf(s.station);return i<0?preferred.length+(secondary.includes(s.station)?0:1):i;
    };
    sites=[...bySite.values()].sort((a,b)=>rank(a.station)-rank(b.station)||a.station.station.localeCompare(b.station.station));
  }
  function visible(stations){
    const size=map.getSize(),point=s=>map.latLngToContainerPoint([s.lat,s.lon]);
    const overlap=(a,b)=>a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;
    const shift=(b,p)=>({...b,left:p.x+b.left,right:p.x+b.right,top:p.y+b.top,bottom:p.y+b.bottom});
    const candidates=[];
    for(const {station,f,frames,radius} of sites){
      if(mode==="clouds"&&!frames[index].length)continue;
      const p=point(station);if(p.x<0||p.y<0||p.x>size.x||p.y>size.y)continue;
      const boxes=(mode==="plots"?frames.flat():frames[index]).map(b=>shift(b,p));
      candidates.push({id:station.station,bounds:shift(f,p),boxes,point:p,radius:(radius||0)*windSpacingFactor,
        reportHours:frames.filter(boxes=>boxes.length).length,conflicts:new Set()});
    }
    const reaches=(circle,label)=>{
      const dx=Math.max(label.left-circle.point.x,0,circle.point.x-label.right);
      const dy=Math.max(label.top-circle.point.y,0,circle.point.y-label.bottom);
      return dx*dx+dy*dy<=circle.radius*circle.radius;
    };
    for(let i=0;i<candidates.length;i++)for(let j=0;j<i;j++){
      const a=candidates[i],b=candidates[j];
      if(!overlap(a.bounds,b.bounds))continue;
      // Use slightly tighter all-bearing spacing and loop-wide label widths.
      // Calm winds and timeline changes cannot temporarily admit a neighbor.
      const body=a.boxes.some(x=>b.boxes.some(y=>overlap(x,y)));
      const sweep=mode==="plots"&&(a.boxes.some(label=>label.kind==="text"&&reaches(b,label))||b.boxes.some(label=>label.kind==="text"&&reaches(a,label)));
      if(body||sweep){a.conflicts.add(b);b.conflicts.add(a);}
    }
    const keep=new Set(),remaining=new Set(candidates);
    const take=site=>{keep.add(site.id);remaining.delete(site);for(const other of site.conflicts)remaining.delete(other);};
    const focus=mode==="plots"?cityPlots.priority:preferred;
    const primary=focus.map(id=>candidates.find(s=>s.id===id)).filter(Boolean);
    // Prefer the largest nonoverlapping subset of the priority locations.
    let best=[];
    for(let mask=0;mask<2**primary.length;mask++){
      const subset=primary.filter((_,i)=>mask&(1<<i));
      if(subset.length<=best.length||subset.some((a,i)=>subset.slice(0,i).some(b=>a.conflicts.has(b))))continue;
      best=subset;
    }
    for(const site of best)take(site);
    for(const site of candidates)if(!focus.includes(site.id)&&primary.some(core=>core.conflicts.has(site)))remaining.delete(site);
    // KSTP wins available space after the core trio, before KSGS or others.
    // KSGS remains eligible when zooming gives both stations room.
    for(const id of secondary){const site=[...remaining].find(s=>s.id===id);if(site)take(site);}
    // Fill remaining gaps with the least-conflicting stations first.
    while(remaining.size){
      let best,degree=Infinity;
      for(const site of remaining){
        let count=0;for(const other of site.conflicts)if(remaining.has(other))count++;
        if(count<degree||count===degree&&site.reportHours>(best?.reportHours||0)){best=site;degree=count;}
      }
      take(best);
    }
    return stations.filter(s=>keep.has(s.station));
  }

  function render(){
    if(el("metar").hidden||moving)return;
    if(!data)return;
    init();
    const hours=data.history;
    if(followLatest){const last=hours.findLastIndex(f=>f.stations.length);index=last<0?hours.length-1:last;}
    index=Math.max(0,Math.min(index,hours.length-1));
    const frame=hours[index];
    const reports=mode==="plots"?data.plots[index]:frame.stations;
    draw(visible(reports));
    const slider=el("metar-timeline");slider.max=String(hours.length-1);slider.value=String(index);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*index/(hours.length-1):0}%`);
    el("metar-time").textContent=`${data._savedCopy?"Saved · ":""}${time.format(new Date(frame.hour))} · ${index+1}/${hours.length}`;
    slider.setAttribute("aria-valuetext",el("metar-time").textContent);
    el("metar-map").setAttribute("aria-label",mode==="clouds"?"Airport sky-cover circles with the lowest BKN or OVC height to the right, in thousands of feet AGL":"Hourly temperature, dewpoint and wind for the Twin Cities average and selected Minnesota airports");
    el("metar-status").textContent=`${reports.length} ${mode==="plots"?"plots":"airport reports"} for this hour${data.stale?" · Background updates delayed":""}`;
  }
  function draw(drawn){
    const keep=new Set(drawn.map(s=>s.station));
    for(const [id,entry] of active)if(!keep.has(id)||entry.mode!==mode){markers.removeLayer(entry.marker);active.delete(id);}
    for(const station of drawn){
      const existing=active.get(station.station);
      if(existing?.station===station&&existing.mode===mode)continue;
      const plots=plotCaches[mode];
      const name=mode==="plots"?cityPlots.names.get(station.station):null;
      const metro=station.station===cityPlots.metroId;
      let cached=plots.get(station);
      if(!cached){
      const plot=mode==="clouds"?model.singleStationModel(station,"clouds"):model.combinedStationModel(station,windPlotOptions),popup=node("div");popup.className="cloud-popup";
      popup.append(node("strong",name?(metro?name:`${name} (${station.station})`):station.station),node("p",station.time?time.format(new Date(station.time)):"Report time unavailable"));
      for(const [label,value] of [["Temperature",station.tempF],["Dewpoint",station.dewpointF]])popup.append(node("p",`${label}: ${Number.isFinite(value)?value.toFixed(1)+"°F":"unavailable"}`));
      const wind=station.wind||{},barb=model.combinedWind(wind,mode!=="clouds"&&windPlotOptions.mphBarbs),layer=model.firstCloudLayer(station);
      popup.append(node("p",`Wind: ${Number.isFinite(barb.speed)?Math.round(barb.speed)+" mph":"unknown"}${Number.isFinite(wind.direction)?" from "+Math.round(wind.direction)+"°":wind.variable?" · variable direction":""}`));
      if(metro){
        popup.append(node("p",`Equal average of ${cityPlots.metroAirports.join(" · ")}`));
      }else{
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
      else {const marker=L.marker([station.lat,station.lon],{icon:cached.icon,title:`${name||station.station} · METAR`,keyboard:true}).bindPopup(cached.popup).addTo(markers);active.set(station.station,{marker,station,mode});}
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
    sourceData=next;data={...next,history,plots:history.map(cityPlots.reports)};
    prepareSpacing();
    const restored=!followLatest&&selected?data.history.findIndex(f=>f.hour===selected):-1;
    index=restored>=0?restored:followLatest?data.history.length-1:0;
    render();
  }
  async function load(force=false){
    if(busy)return;busy=true;el("refresh-metar").disabled=true;
    try{adopt(await window.WeatherPrepared.read("/api/station-plots?view=loop",{force}));}
    catch(error){
      const message=`${error.message}${data?" Previous reports retained.":""}`;
      el("metar-status").textContent=message;
      if(!data)el("metar-time").textContent="Hourly history recovering…";
    }
    finally{busy=false;el("refresh-metar").disabled=false;}
  }
  window.WeatherPrepared.subscribe("/api/station-plots?view=loop",adopt);
  function selectProduct(product){
    const previous=mode;
    mode=product==="clouds"?"clouds":defaultProduct;
    el("metar-product").value=mode;
    el("metar-eyebrow").textContent=mode==="plots"?"MINNESOTA · HOURLY METARS":"AIRPORT METARS · UPPER MIDWEST";
    if(data)prepareSpacing();
    if(map&&(previous!==mode||window.WeatherDefaultViews?.savedMetar?.(mode)))reset();
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
    selectProduct(defaultProduct);
    setTimeout(()=>map?.invalidateSize({pan:false}),0);
  }},refresh(){render();load();}};
})();
