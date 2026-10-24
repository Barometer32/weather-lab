"use strict";
// Both observation maps read the same prepared hourly airport reports.
window.WeatherCloudHeights = (() => {
  const el=id=>document.getElementById(id),model=window.WeatherStationModel;
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let map,markers,data,busy=false,index=0,followLatest=true;
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  function reset(){map?.setView([44.925,-93.35],map.getSize().x<600?9:8.5);}
  function init(){
    if(map)return;
    map=L.map("cloud-height-map",{minZoom:5,maxZoom:13,zoomSnap:.25,zoomDelta:.25,wheelPxPerZoomLevel:90});
    reset();
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(map);
    markers=L.layerGroup().addTo(map);map.on("moveend",render);
  }
  function description(station){
    const layer=model.firstCloudLayer(station);
    if(layer)return `${model.cloudHeightText(station)} · ${layer.baseFtAGL.toLocaleString()} ft AGL (${layer.cover})`;
    const layers=model.cloudLayers(station);
    return layers.some(l=>["BKN","OVC"].includes(l.cover))?"BKN/OVC height unavailable":layers.length?"No reported BKN/OVC layer":"Cloud report unavailable";
  }
  function visibleSites(stations){
    // Reserve each airport's widest height over all frames, so labels do not
    // change neighboring visibility when the history slider moves.
    const sites=new Map(),size=map.getSize(),accepted=new Set(),boxes=[],gap=.75;
    for(const hour of data.history)for(const station of hour.stations){
      const label=model.cloudHeightText(station);if(!label)continue;
      const old=sites.get(station.station);
      sites.set(station.station,{station,half:Math.max(old?.half||0,model.cloudFootprint(station).right)});
    }
    const priority=["KFCM","KMIC","KMSP"];
    const rank=s=>priority.includes(s.station)?priority.indexOf(s.station):priority.length;
    const candidates=[...sites.values()].sort((a,b)=>rank(a.station)-rank(b.station)||a.station.station.localeCompare(b.station.station));
    const inView=station=>{const p=map.latLngToContainerPoint([station.lat,station.lon]);return p.x>=0&&p.y>=0&&p.x<=size.x&&p.y<=size.y;};
    for(const {station,half} of candidates){
      if(!inView(station))continue;
      const p=map.latLngToContainerPoint([station.lat,station.lon]);
      const box={left:p.x-half,right:p.x+half,top:p.y-7,bottom:p.y+7};
      if(boxes.some(b=>box.left<b.right+gap&&box.right>b.left-gap&&box.top<b.bottom+gap&&box.bottom>b.top-gap))continue;
      boxes.push(box);accepted.add(station.station);
    }
    return {drawn:stations.filter(s=>model.cloudHeightText(s)&&accepted.has(s.station)),
      inView:stations.filter(s=>model.cloudHeightText(s)&&inView(s)).length};
  }
  function render(){
    if(!data)return;
    init();markers.clearLayers();
    const hours=data.history;
    if(followLatest){const available=hours.findLastIndex(h=>h.stations.length);index=available<0?hours.length-1:available;}
    index=Math.max(0,Math.min(index,hours.length-1));
    const frame=hours[index],stations=frame.stations;
    const {drawn,inView}=visibleSites(stations);
    const eligible=stations.filter(s=>model.cloudHeightText(s)).length;
    for(const station of drawn){
      const label=model.cloudHeightText(station);
      if(!label)continue;
      // Only a tiny label-sized gap is reserved, for denser plots than METAR.
      const popup=node("div");popup.className="cloud-popup";
      popup.append(node("strong",station.station),node("p",station.time?time.format(new Date(station.time)):"Report time unavailable"),node("p",`Lowest BKN/OVC: ${description(station)}`));
      for(const layer of model.cloudLayers(station))popup.append(node("p",`${layer.cover}: ${layer.baseFtAGL==null?"height unknown":layer.baseFtAGL.toLocaleString()+" ft AGL"}`));
      const icon=L.divIcon({className:"weather-station",html:`<span class="cloud-ceiling-number">${label}</span>`,iconSize:[32,24],iconAnchor:[16,12]});
      L.marker([station.lat,station.lon],{icon,title:`${station.station} · ${description(station)}`,keyboard:true}).bindPopup(popup).addTo(markers);
    }
    const slider=el("clouds-timeline");slider.max=String(hours.length-1);slider.value=String(index);slider.disabled=hours.length<2;
    slider.style.setProperty("--progress",`${hours.length>1?100*index/(hours.length-1):0}%`);
    el("clouds-time").textContent=`${time.format(new Date(frame.hour))} · hourly ${index+1}/${hours.length}`;
    slider.setAttribute("aria-valuetext",el("clouds-time").textContent);
    el("clouds-status").textContent=`${drawn.length} cloud heights in view${inView>drawn.length?` · ${inView-drawn.length} nearby heights hidden for spacing; zoom in`:""} · ${eligible} airports with BKN/OVC heights / ${stations.length} airport reports · ${hours.filter(h=>h.stations.length).length}/12 hours with reports${!hours.at(-1).stations.length?" · Waiting for the newest hour; showing the latest available reports":""}${data.stale?" · Background updates delayed":""}`;
    el("clouds-rows").replaceChildren();
    if(el("clouds-station-list").open){
      const query=el("clouds-search").value.trim().toUpperCase();
      for(const station of stations){
        if(query&&!`${station.station} ${station.name||""}`.toUpperCase().includes(query))continue;
        const row=node("tr"),cell=node("td"),button=node("button",station.station);button.className="station-link";
        button.addEventListener("click",()=>{map.setView([station.lat,station.lon],10);el("cloud-height-map").scrollIntoView({behavior:"smooth",block:"center"});});cell.append(button);
        row.append(cell,node("td",station.time?time.format(new Date(station.time)):"Unavailable"),node("td",description(station)));el("clouds-rows").append(row);
      }
    }
  }
  async function load(){
    if(busy)return;busy=true;el("refresh-clouds").disabled=true;
    try{
      const r=await fetch("/api/station-plots",{cache:"no-store"}),next=await r.json();
      if(!r.ok)throw Error(next.error||"Cloud reports unavailable");
      const selected=data?.history[index]?.hour;data=next;
      const restored=!followLatest&&selected?data.history.findIndex(h=>h.hour===selected):-1;
      index=restored>=0?restored:followLatest?data.history.length-1:0;
      if(data.serverTime)window.WeatherSun?.sync(data.serverTime);
      render();
    }catch(error){el("clouds-status").textContent=`${error.message}${data?" Previous reports retained; check their timestamps.":""}`;}
    finally{busy=false;el("refresh-clouds").disabled=false;}
  }
  function select(id){
    if(id!=="clouds")return;
    if(data){render();map.invalidateSize({pan:false});}
    load();setTimeout(()=>map?.invalidateSize({pan:false}),0);
  }
  el("refresh-clouds").addEventListener("click",load);
  el("clouds-timeline").addEventListener("input",event=>{index=Number(event.target.value);followLatest=index===data.history.length-1;render();});
  el("clouds-reset").addEventListener("click",reset);
  el("clouds-search").addEventListener("input",render);
  el("clouds-station-list").addEventListener("toggle",()=>{if(el("clouds-station-list").open)render();});
  window.WeatherFullscreen.attach({surfaceId:"clouds-surface",buttonId:"clouds-fullscreen",label:"cloud heights map",onResize:()=>{if(map){map.invalidateSize({pan:false});render();}}});
  setInterval(()=>{if(!document.hidden&&!el("clouds").hidden)load();},60000);
  return {select};
})();
