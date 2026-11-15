"use strict";
window.WeatherRapmet=(()=>{
  const el=id=>document.getElementById(id),model=window.WeatherStationModel,endpoint="/api/rapmet";
  const options={dot:true,mphBarbs:true,celsius:true},preferred=["KMSP","KFCM","KMIC"];
  const locations={KMSP:[44.8852,-93.2313],KFCM:[44.8321,-93.4705],KMIC:[45.0623,-93.3511]};
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  let map,layer,data,active=false,busy=false;const markers=new Map();
  const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
  const rows=()=> (data?.stations||[]).filter(s=>s.station!=="KSTP"&&["ND","SD","IA","MN","WI"].includes(s.state)&&s.reportType==="HFMETAR"&&Number.isFinite(s.tempC)&&Number.isFinite(s.dewpointC)&&Date.now()-Date.parse(s.time)<=3600000);
  function sites(){
    const list=rows().map(station=>({station,...model.combinedReservation(station,options)}));
    for(const id of preferred)if(!list.some(s=>s.station.station===id)){
      const [lat,lon]=locations[id],station={station:id,lat,lon,tempC:-99,dewpointC:-99};
      list.push({station,...model.combinedReservation(station,options),reserveOnly:true});
    }
    return list;
  }
  function reset(){
    if(!map)return;
    const list=sites().map(s=>({...s,f:s.bounds}));
    const view=window.WeatherDefaultViews?.savedMetar("rapmet")||window.WeatherDefaultViews?.metar(list,map.getSize())||{center:[44.945,-93.343],zoom:9};
    map.setView(view.center,view.zoom,{animate:false});
  }
  function init(){
    if(map)return;
    map=L.map("rapmet-map",{minZoom:5,maxZoom:13,zoomSnap:.25,zoomDelta:.25,wheelPxPerZoomLevel:90});reset();
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(map);
    layer=L.layerGroup().addTo(map);map.on("moveend",render);
  }
  function visible(){
    const size=map.getSize(),shift=(b,p)=>({...b,left:p.x+b.left,right:p.x+b.right,top:p.y+b.top,bottom:p.y+b.bottom});
    const overlap=(a,b)=>a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;
    const list=sites().map(s=>{const point=map.latLngToContainerPoint([s.station.lat,s.station.lon]);return {...s,id:s.station.station,point,boxes:s.boxes.map(b=>shift(b,point)),radius:s.radius*.90,conflicts:new Set()};})
      .filter(s=>s.point.x>=0&&s.point.y>=0&&s.point.x<=size.x&&s.point.y<=size.y);
    const reaches=(a,b)=>{const dx=Math.max(b.left-a.point.x,0,a.point.x-b.right),dy=Math.max(b.top-a.point.y,0,a.point.y-b.bottom);return dx*dx+dy*dy<=a.radius*a.radius;};
    for(let i=0;i<list.length;i++)for(let j=0;j<i;j++){
      const a=list[i],b=list[j];
      if(a.boxes.some(x=>b.boxes.some(y=>overlap(x,y)))||a.boxes.some(x=>x.kind==="text"&&reaches(b,x))||b.boxes.some(x=>x.kind==="text"&&reaches(a,x))){a.conflicts.add(b);b.conflicts.add(a);}
    }
    const keep=new Set(),remaining=new Set(list),take=s=>{keep.add(s.id);remaining.delete(s);for(const c of s.conflicts)remaining.delete(c);};
    const primary=preferred.map(id=>list.find(s=>s.id===id)).filter(Boolean);
    let best=[];
    const available=primary.filter(s=>!s.reserveOnly);
    for(let mask=0;mask<2**available.length;mask++){
      const subset=available.filter((_,i)=>mask&(1<<i));
      if(subset.length>best.length&&!subset.some((a,i)=>subset.slice(0,i).some(b=>a.conflicts.has(b))))best=subset;
    }
    for(const s of best)take(s);
    for(const s of list)if(s.reserveOnly||!preferred.includes(s.id)&&primary.some(p=>p.conflicts.has(s)))remaining.delete(s);
    while(remaining.size){let chosen,degree=Infinity;for(const s of remaining){const d=[...s.conflicts].filter(c=>remaining.has(c)).length;if(d<degree){chosen=s;degree=d;}}take(chosen);}
    return list.filter(s=>keep.has(s.id)&&!s.reserveOnly).map(s=>s.station);
  }
  function render(){
    if(!active||el("metar").hidden||!data)return;
    init();const drawn=visible(),keep=new Set(drawn.map(s=>s.station));
    for(const [id,marker] of markers)if(!keep.has(id)){layer.removeLayer(marker);markers.delete(id);}
    for(const s of drawn){
      const plot=model.combinedStationModel(s,options),popup=node("div","");popup.className="cloud-popup";
      const age=Math.max(0,Math.floor((Date.now()-Date.parse(s.time))/60000)),w=s.wind||{};
      const wind=Number.isFinite(w.speedMph)?w.speedMph<.5?"Calm":`${Number.isFinite(w.direction)?directions[Math.round(w.direction/45)%8]:w.variable?"VRB":"Unknown"} ${Math.round(w.speedMph)} mph`:"Unavailable";
      for(const [tag,text] of [["strong",`${s.station} · ${s.name||s.state}`],["p",`${time.format(new Date(s.time))} · ${age} min old`],["p",`Temperature: ${Math.round(s.tempC)}°C`],["p",`Dewpoint: ${Math.round(s.dewpointC)}°C`],["p",`Wind: ${wind}`],["p",s.source]])popup.append(node(tag,text));
      const icon=L.divIcon({className:"weather-station",html:plot.html,iconSize:plot.size,iconAnchor:plot.anchor});
      const old=markers.get(s.station);
      if(old)old.setIcon(icon).setLatLng([s.lat,s.lon]).setPopupContent(popup);
      else markers.set(s.station,L.marker([s.lat,s.lon],{icon,title:`${s.station} · five-minute ASOS · ${time.format(new Date(s.time))}`,keyboard:true}).bindPopup(popup).addTo(layer));
    }
    const available=rows(),newest=available.map(s=>s.time).sort().at(-1),age=newest?Math.max(0,Math.floor((Date.now()-Date.parse(newest))/60000)):null;
    el("rapmet-time").textContent=newest?`${time.format(new Date(newest))} · ${age} min old · ${available.length} airports · °C · mph${age>15||data.sourceDelayed?" · Source delayed":""}${data.stale?" · Collector delayed":""}${data._savedCopy?" · Saved":""}`:"No eligible five-minute reports in the last hour";
  }
  function adopt(next){
    if(!Array.isArray(next.stations))throw Error("Five-minute reports are not ready");
    if(data&&next.checkedAt<data.checkedAt)return;
    data=next;render();if(next.serverTime&&!next._savedCopy)window.WeatherSun?.sync(next.serverTime);
  }
  async function load(force=false){
    if(busy)return;busy=true;if(active)el("refresh-metar").disabled=true;
    try{adopt(await window.WeatherPrepared.read(endpoint,{force}));}
    catch(e){if(active)el("rapmet-time").textContent=data?el("rapmet-time").textContent+" · Refresh unavailable":e.message;}
    finally{busy=false;if(active)el("refresh-metar").disabled=false;}
  }
  el("rapmet-reset").addEventListener("click",reset);
  el("rapmet-set-default").addEventListener("click",()=>{
    if(!map)return;const c=map.getCenter(),b=el("rapmet-set-default");b.textContent=window.WeatherDefaultViews?.saveMetar("rapmet",[c.lat,c.lng],map.getZoom())?"Default saved":"Could not save";setTimeout(()=>{b.textContent="Set default";},2000);
  });
  window.WeatherFullscreen.attach({surfaceId:"rapmet-surface",buttonId:"rapmet-fullscreen",label:"RAPMET map",onResize:()=>{map?.invalidateSize({pan:false});render();}});
  window.WeatherPrepared.subscribe(endpoint,adopt);
  setInterval(()=>{if(active&&!document.hidden&&!el("metar").hidden)load(true);},300000);
  setInterval(()=>{if(active&&!document.hidden)render();},60000);
  window.addEventListener("weather-layout-resize",()=>{if(active)map?.invalidateSize({pan:false});});
  return {load,select(mode){active=mode==="rapmet";if(active){init();render();load();setTimeout(()=>map.invalidateSize({pan:false}),0);}}};
})();
