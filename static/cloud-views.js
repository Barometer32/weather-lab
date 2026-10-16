"use strict";
// One official hourly METAR station map; visitors read prepared data only.
window.WeatherCloudViews = (() => {
  const el=id=>document.getElementById(id);
  const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  let metarMap,markers,data,busy=false,index=0,retryTimer,hourTimer,waitUntil=0;
  const excluded=new Set(["KCFE","KFCE","KSGS"]);
  const preferred=["KFCM","KMIC","KMSP","KMKT","KRWF","KSTC","KAXN","KDLH","KRST","KBRD","KFAR","KABR","KFSD","KDSM","KLSE","KEAU","KMCW","KMSN","KSTP"];
  const plotScale=.82,directions=["N","NE","E","SE","S","SW","W","NW"];
  const rounded=v=>v==null?"—":String(Math.round(v));
  const windMph=w=>w?.speedMph??(w?.speedKnots==null?null:w.speedKnots*1.150779);
  const windText=w=>windMph(w)==null?"—":windMph(w)<.5?"Calm":`${w.direction==null?(w.variable?"Variable":"?"):directions[Math.round(w.direction/45)%8]} ${rounded(windMph(w))} mph`;
  function node(tag,text,className){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(className)n.className=className;return n;}
  function stationModel(station) {
    const wind=station.wind, speed=windMph(wind);
    let arrow;
    if(speed!=null&&speed>=.5&&wind.direction!=null){
      // METAR degrees describe where wind comes FROM; the arrow points TO.
      const toward=(wind.direction+180)%360,path="M0 9V-9M-3 -4L0 -9L3 -4";
      arrow=`<g class="wind-arrow" transform="translate(30 24) rotate(${toward})" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="${path}" stroke="white" stroke-width="4.5"/><path d="${path}" stroke="#111" stroke-width="1.7"/></g>`;
    }else{
      const label=speed==null?"?":speed<.5?"Calm":wind.variable?"VRB":"?";
      arrow=`<text class="plot-wind-state" x="30" y="27" text-anchor="middle">${label}</text>`;
    }
    return `<svg class="metar-plot" width="${84*plotScale}" height="${44*plotScale}" viewBox="0 0 84 44" aria-hidden="true">${arrow}<text class="plot-temp" x="17" y="16" text-anchor="end">${rounded(station.tempF)}</text><text class="plot-dew" x="17" y="37" text-anchor="end">${rounded(station.dewpointF)}</text><text class="plot-speed" x="44" y="29">${rounded(speed)}</text></svg>`;
  }
  function initMetars() {
    if(metarMap)return;
    metarMap=L.map("metar-cloud-map",{minZoom:5,maxZoom:13,zoomSnap:.1,zoomDelta:.1});
    resetMetarView();
    for(const [kind,opacity] of [["uscounties",.2],["usstates",.8]])L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${kind}/{z}/{x}/{y}.png`,{opacity,attribution:"Boundaries: Iowa Environmental Mesonet"}).addTo(metarMap);
    markers=L.layerGroup().addTo(metarMap);
    const density=()=>el("metar-cloud-map").classList.toggle("compact-clouds",metarMap.getZoom()<8);
    metarMap.on("zoomend",density);
    metarMap.on("moveend",renderMetars);density();
  }
  function resetMetarView() {
    // The in-between desktop zoom keeps all three focus airports separated
    // while showing more surroundings than the previous close metro view.
    metarMap?.setView([44.925,-93.35],metarMap.getSize().x<600?9:8.5);
  }
  function plotStations(stations) {
    const candidates=stations.filter(s=>!excluded.has(s.station));
    const priority=s=>{const rank=preferred.indexOf(s.station);return rank<0?preferred.length:rank;};
    candidates.sort((a,b)=>priority(a)-priority(b)||a.station.localeCompare(b.station));
    const size=metarMap.getSize(),accepted=[],boxes=[];
    for(const station of candidates){
      const point=metarMap.latLngToContainerPoint([station.lat,station.lon]);
      if(point.x<0||point.y<0||point.x>size.x||point.y>size.y)continue;
      // Bound the actual labels and short arrow, including white halos and a
      // small gap. Two-digit plots can be closer than long/negative readings.
      const digits=Math.max(rounded(station.tempF).length,rounded(station.dewpointF).length);
      const box={left:point.x+(17-digits*9-30-5)*plotScale,right:point.x+(44+rounded(windMph(station.wind)).length*9-30+5)*plotScale,
        top:point.y-24*plotScale,bottom:point.y+22*plotScale};
      if(boxes.some(b=>box.left<b.right&&box.right>b.left&&box.top<b.bottom&&box.bottom>b.top))continue;
      boxes.push(box);accepted.push(station);
    }
    return accepted;
  }
  function renderMetars(){
    if(!data)return;
    initMetars();markers.clearLayers();
    index=Math.max(0,Math.min(index,data.history.length-1));
    const selected=data.history[index],stations=selected.stations.filter(s=>!excluded.has(s.station));
    const drawn=plotStations(stations),slider=el("metar-cloud-timeline");
    slider.max=String(data.history.length-1);slider.value=String(index);slider.disabled=data.history.length<2;
    slider.style.setProperty("--progress",`${data.history.length>1?100*index/(data.history.length-1):0}%`);
    el("metar-cloud-time").textContent=`${time.format(new Date(selected.hour))} · hour ${index+1}/${data.history.length}`;
    slider.setAttribute("aria-valuetext",el("metar-cloud-time").textContent);
    for(const s of drawn){
      const popup=node("div",null,"cloud-popup");
      popup.append(node("strong",s.station));
      if(s.name&&s.name!==s.station)popup.append(node("p",s.name));
      popup.append(node("p",time.format(new Date(s.time))),node("p","Routine airport METAR · NOAA Aviation Weather Center"),
        node("p",`Temperature ${s.tempF==null?"—":s.tempF.toFixed(1)}°F · Dew point ${s.dewpointF==null?"—":s.dewpointF.toFixed(1)}°F`),
        node("p",`Wind from ${windText(s.wind)}`));
      if(s.rawOb)popup.append(node("p",s.rawOb));
      const icon=L.divIcon({className:"weather-station",html:stationModel(s),iconSize:[84*plotScale,44*plotScale],iconAnchor:[30*plotScale,24*plotScale]});
      L.marker([s.lat,s.lon],{icon,title:`${s.station} · ${rounded(s.tempF)}°F / ${rounded(s.dewpointF)}°F · ${windText(s.wind)}`,keyboard:true}).bindPopup(popup).addTo(markers);
    }
    const query=el("metar-cloud-search").value.trim().toUpperCase();el("metar-cloud-rows").replaceChildren();
    if(el("metar-station-list").open)for(const s of stations){
      if(query&&!`${s.station} ${s.name||""}`.toUpperCase().includes(query))continue;
      const row=node("tr"),cell=node("td"),button=node("button",s.station,"station-link");
      button.addEventListener("click",()=>{metarMap.setView([s.lat,s.lon],10);el("metar-cloud-map").scrollIntoView({behavior:"smooth",block:"center"});});
      cell.append(button);row.append(cell,node("td",time.format(new Date(s.time))),node("td",`${rounded(s.tempF)} / ${rounded(s.dewpointF)} °F · ${windText(s.wind)}`));
      el("metar-cloud-rows").append(row);
    }
    const health=el("station-feed-status");health.hidden=false;
    health.textContent=data.stale?"Hourly METAR update delayed. Showing saved reports with their actual timestamps.":stations.length?`NOAA airport METARs · ${stations.length} eligible reports for this hour`:"No eligible METARs saved for this hour. Initial history backfill may still be running.";
    el("metar-cloud-status").textContent=`${drawn.length} spaced plots visible · ${stations.length} reporting airports · :50–:59 reports · updates hourly at :05${data.stale?" · Background updates delayed":""}`;
  }
  function retry(){
    clearTimeout(retryTimer);
    if(Date.now()<waitUntil)retryTimer=setTimeout(()=>{if(!document.hidden&&!el("metar-clouds").hidden)loadMetars();},60000);
  }
  async function loadMetars(){
    if(busy)return;busy=true;el("refresh-metar-clouds").disabled=true;
    try{
      const selected=data?.history[index]?.hour,followLatest=!data||index===data.history.length-1;
      const response=await fetch("/api/station-plots",{cache:"no-store"}),fresh=await response.json();
      if(!response.ok)throw Error(fresh.error||"METAR reports unavailable");
      data=fresh;
      const restored=!followLatest&&selected?data.history.findIndex(h=>h.hour===selected):-1;
      index=restored>=0?restored:followLatest?data.history.length-1:0;
      renderMetars();
      const now=new Date(),due=new Date(now);due.setUTCMinutes(5,0,0);
      if(due>now)due.setUTCHours(due.getUTCHours()-1);
      if(new Date(data.checkedAt)<due)retry();else{waitUntil=0;clearTimeout(retryTimer);}
    }catch(error){el("metar-cloud-status").textContent=`${error.message}${data?" Saved reports retained; check their timestamps.":""}`;retry();}
    finally{busy=false;el("refresh-metar-clouds").disabled=false;}
  }
  function schedule(){
    clearTimeout(hourTimer);
    const interval=3600000,offset=5*60000+30000;
    const next=(Math.floor((Date.now()-offset)/interval)+1)*interval+offset;
    hourTimer=setTimeout(()=>{
      if(!document.hidden&&!el("metar-clouds").hidden){waitUntil=Date.now()+3*60000;loadMetars();}
      schedule();
    },next-Date.now());
  }
  function select(id){if(id==="metar-clouds"){initMetars();waitUntil=Date.now()+3*60000;loadMetars();schedule();setTimeout(()=>metarMap?.invalidateSize(),0);}}
  el("refresh-metar-clouds").addEventListener("click",loadMetars);
  el("metar-cloud-search").addEventListener("input",renderMetars);
  el("metar-station-list").addEventListener("toggle",()=>{if(el("metar-station-list").open)renderMetars();});
  el("metar-cloud-reset").addEventListener("click",resetMetarView);
  el("metar-cloud-timeline").addEventListener("input",event=>{index=Number(event.target.value);renderMetars();});
  schedule();
  return {select};
})();
