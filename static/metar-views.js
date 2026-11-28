"use strict";
// One hourly METAR feed shared by the regional plots and the CLOUDS map.
window.WeatherMetars = (() => {
  const el=id=>document.getElementById(id),model=window.WeatherStationModel;
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let map,markers,data,index=0,followLatest=true,moving=false,sites=[],mode="plots",wantedHour=null;
  const historyHours=4;
  const preferred=["KMSP","KFCM","KMIC"];
  const secondary=["KSTP"];
  const metroId="METRO";
  // Equidistant from the three airport locations in the METAR feed.
  const metroPosition={lat:44.9411045,lon:-93.3874109};
  // Prioritize the major cities at wide zooms. Smaller regional airports
  // provide coverage where those cities are farther apart.
  const regionalHubs=new Map([
    ["KMKE","Milwaukee"],["KDSM","Des Moines"],["KMSN","Madison"],
    ["KFSD","Sioux Falls"],["KFAR","Fargo"],["KGRB","Green Bay"],
    ["KCID","Cedar Rapids"],["KRST","Rochester"],["KDLH","Duluth"],
    ["KDVN","Davenport"],["KSUX","Sioux City"],
    ["KSTC","St. Cloud"],["KALO","Waterloo"],["KEAU","Eau Claire"],
    ["KGFK","Grand Forks"],["KLSE","La Crosse"],["KMKT","Mankato"],
    // Minnesota
    ["KRWF","Redwood Falls"],["KAXN","Alexandria"],["KBRD","Brainerd"],
    ["KBJI","Bemidji"],["KHIB","Hibbing"],["KINL","International Falls"],
    ["KTVF","Thief River Falls"],["KROX","Roseau"],["KCKC","Grand Marais"],
    ["KVVV","Ortonville"],["KMWM","Windom"],
    // Wisconsin
    ["KAUW","Wausau"],["KRHI","Rhinelander"],["KASX","Ashland"],
    ["KHYR","Hayward"],["KFLD","Fond du Lac"],["KSUE","Sturgeon Bay"],
    // Iowa
    ["KCBF","Council Bluffs"],["KDNS","Denison"],["KSPW","Spencer"],
    ["KFOD","Fort Dodge"],["KMCW","Mason City"],["KDBQ","Dubuque"],
    ["KOTM","Ottumwa"],["KBRL","Burlington"],
    // North Dakota
    ["KJMS","Jamestown"],["KDVL","Devils Lake"],
    // South Dakota
    ["KABR","Aberdeen"],["KATY","Watertown"],["KHON","Huron"],
    ["KYKN","Yankton"],["K9V9","Chamberlain"],
    // Fill gaps after the existing regional hubs have been placed.
    ["KBDH","Willmar"],["KMML","Marshall"],["KHCD","Hutchinson"],
    ["KAEL","Albert Lea"],
    ["KRPD","Rice Lake"],["KISW","Wisconsin Rapids"],
    ["KMIW","Marshalltown"],["KMHE","Mitchell"],["KBWP","Wahpeton"],
  ]);
  const regionalView=[[40.5,-100],[49.4,-86.6]];
  const windPlotOptions={dot:true,mphBarbs:true,compact:true};
  const barbEdgeOverlap=4; // Screen pixels, including the symbol halos.
  let busy=false,sourceData;
  const plotCaches={plots:new WeakMap(),clouds:new WeakMap()};
  const cloudAvailable=station=>["CLR","SKC","NSC","NCD","CAVOK","FEW","SCT","BKN","OVC","VV"].includes(model.skyCode(station))&&model.cloudPlotLabel(station)!=="?";
  const active=new Map();
  const panelFor=product=>el(product==="clouds"?"clouds":"metar");
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  function reset(){
    if(!map)return;
    const saved=window.WeatherDefaultViews?.savedMetar?.(mode);
    if(mode==="plots"&&!saved){
      map.fitBounds(regionalView,{padding:[32,32],animate:false});
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
  function average(values){
    return values.every(Number.isFinite)?values.reduce((sum,value)=>sum+value,0)/values.length:null;
  }
  function metroPlot(reports,hour){
    const airports=preferred.map(id=>reports.find(report=>report.station===id));
    if(airports.some(report=>!report))return null;
    const winds=airports.map(report=>report.wind||{});
    const speeds=winds.map(wind=>Number.isFinite(wind.speedKnots)?wind.speedKnots*1.150779:wind.speedMph);
    let east=0,north=0,directions=0;
    for(const [i,wind] of winds.entries()){
      const speed=speeds[i];
      if(wind.variable||!Number.isFinite(wind.direction)||!Number.isFinite(speed)||speed<=0)continue;
      const radians=wind.direction*Math.PI/180;
      east+=speed*Math.sin(radians);north+=speed*Math.cos(radians);directions++;
    }
    const direction=Math.hypot(east,north)>.01?(Math.atan2(east,north)*180/Math.PI+360)%360:null;
    return {station:metroId,...metroPosition,time:hour,
      tempF:average(airports.map(report=>report.tempF)),
      dewpointF:average(airports.map(report=>report.dewpointF)),
      wind:{speedMph:average(speeds),direction,variable:direction===null&&(directions>0||winds.some(wind=>wind.variable))}};
  }
  function regionalPlots(frame){
    const reports=frame.stations.filter(report=>report.reportType==="METAR");
    const plots=reports.filter(report=>regionalHubs.has(report.station));
    const metro=metroPlot(reports,frame.hour);
    return metro?[metro,...plots]:plots;
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
      candidates.push({id:station.station,bounds:shift(f,p),boxes,point:p,radius:Math.max(0,radius-barbEdgeOverlap),
        reportHours:frames.filter(boxes=>boxes.length).length,conflicts:new Set()});
    }
    const circleHitsBox=(x,y,radius,box)=>{
      const dx=Math.max(box.left-x,0,x-box.right);
      const dy=Math.max(box.top-y,0,y-box.bottom);
      return dx*dx+dy*dy<radius*radius;
    };
    const coversReading=(station,label)=>{
      const {x,y}=station.point;
      return circleHitsBox(x,y,station.radius,label);
    };
    for(let i=0;i<candidates.length;i++)for(let j=0;j<i;j++){
      const a=candidates[i],b=candidates[j];
      if(!overlap(a.bounds,b.bounds))continue;
      const body=a.boxes.some(x=>b.boxes.some(y=>overlap(x,y)));
      // Reserve every possible wind bearing through the timeline. Barbs can
      // cross each other and skim labels, while deeper contact hides a plot.
      const wind=mode==="plots"&&(a.boxes.some(label=>label.kind==="text"&&coversReading(b,label))
        ||b.boxes.some(label=>label.kind==="text"&&coversReading(a,label)));
      if(body||wind){a.conflicts.add(b);b.conflicts.add(a);}
    }
    const keep=new Set(),remaining=new Set(candidates);
    const take=site=>{keep.add(site.id);remaining.delete(site);for(const other of site.conflicts)remaining.delete(other);};
    const focus=mode==="plots"?[metroId]:preferred;
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
    const nextPriority=mode==="plots"?regionalHubs.keys():secondary;
    for(const id of nextPriority){const site=[...remaining].find(s=>s.id===id);if(site)take(site);}
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
    if(panelFor(mode).hidden||moving)return;
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
    el("metar-map").setAttribute("aria-label",mode==="clouds"?"Airport sky-cover circles with the lowest BKN or OVC height to the right, in thousands of feet AGL":"Hourly regional airport plots and Twin Cities average with wind barbs in mph");
    el("metar-status").textContent=`${reports.length} ${mode==="plots"?"plots":"airport reports"} for this hour${data.stale?" · Background updates delayed":""}`;
  }
  function draw(drawn){
    const keep=new Set(drawn.map(s=>s.station));
    for(const [id,entry] of active)if(!keep.has(id)||entry.mode!==mode){markers.removeLayer(entry.marker);active.delete(id);}
    for(const station of drawn){
      const existing=active.get(station.station);
      if(existing?.station===station&&existing.mode===mode)continue;
      const plots=plotCaches[mode];
      const metro=station.station===metroId;
      const name=mode==="plots"?regionalHubs.get(station.station):null;
      let cached=plots.get(station);
      if(!cached){
      const plot=mode==="clouds"?model.singleStationModel(station,"clouds"):model.combinedStationModel(station,windPlotOptions),popup=node("div");popup.className="cloud-popup";
      const label=metro?"Twin Cities average (KMSP · KFCM · KMIC)":name?`${name} (${station.station})`:station.station;
      popup.append(node("strong",label),node("p",station.time?time.format(new Date(station.time)):"Report time unavailable"));
      for(const [label,value] of [["Temperature",station.tempF],["Dewpoint",station.dewpointF]])popup.append(node("p",`${label}: ${Number.isFinite(value)?value.toFixed(1)+"°F":"unavailable"}`));
      const wind=station.wind||{},mph=mode==="plots",barb=model.combinedWind(wind,mph,mph),layer=model.firstCloudLayer(station);
      const speed=barb.speed;
      popup.append(node("p",`Wind: ${Number.isFinite(speed)?Math.round(speed)+" mph":"unknown"}${Number.isFinite(wind.direction)?" from "+Math.round(wind.direction)+"°":wind.variable?" · variable direction":""}`));
      if(!metro){
        popup.append(node("p",`Cloud cover: ${model.skyCode(station)||"unavailable"}`));
        popup.append(node("p",layer?`${layer.cover}: ${layer.baseFtAGL.toLocaleString()} ft AGL`:model.cloudPlotLabel(station)==="?"?"Cloud report or ceiling height unavailable":"No BKN/OVC layer reported"));
      }
      if(barb.kind==="barb")popup.append(node("p",`Barb feathers: ${mph?`${barb.roundedMph} mph`:`${barb.roundedKnots} kt (nearest 5 kt)`}`));
      const icon=L.divIcon({className:"weather-station",html:plot.html,iconSize:plot.size,iconAnchor:plot.anchor});
      cached={icon,popup};plots.set(station,cached);
      }
      if(existing){existing.marker.setIcon(cached.icon).setLatLng([station.lat,station.lon]).setPopupContent(cached.popup);existing.station=station;existing.mode=mode;}
      else {const marker=L.marker([station.lat,station.lon],{icon:cached.icon,title:`${station.station} · METAR`,keyboard:true}).bindPopup(cached.popup).addTo(markers);active.set(station.station,{marker,station,mode});}
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
    sourceData=next;data={...next,history,plots:history.map(regionalPlots)};
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
    if(previous!==product){
      // Reuse the map and timeline in both tab panels. Leaflet and the
      // controls stay attached to the same DOM nodes.
      mode=product;
      panelFor(mode).append(...panelFor(previous).children);
    }
    el("metar-title").textContent=mode==="plots"?"METAR":"CLOUDS";
    el("metar-eyebrow").textContent=mode==="plots"?"UPPER MIDWEST · HOURLY METARS · WIND MPH":"AIRPORT METARS · UPPER MIDWEST";
    if(data)prepareSpacing();
    if(map&&(previous!==mode||window.WeatherDefaultViews?.savedMetar?.(mode)))reset();
    render();
    load();
  }
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
  window.WeatherFullscreen.attach({surfaceId:"metar-surface",buttonId:"metar-fullscreen",label:"weather map",onResize:()=>{if(map&&!panelFor(mode).hidden){map.invalidateSize({pan:false});render();}}});
  setInterval(()=>{if(!document.hidden&&!panelFor(mode).hidden)load();},30000);
  window.addEventListener("weather-layout-resize",()=>{if(map&&!panelFor(mode).hidden)map.invalidateSize({pan:false});});
  return {select(id){if(id==="metar"||id==="clouds"){
    selectProduct(id==="clouds"?"clouds":"plots");
    setTimeout(()=>map?.invalidateSize({pan:false}),0);
  }},refresh(){render();load();}};
})();
