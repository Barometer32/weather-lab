"use strict";
window.WeatherConditions=(()=>{
  const el=id=>document.getElementById("conditions-"+id),endpoint="/api/conditions",model=window.WeatherConditionsModel;
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  const finite=value=>typeof value==="number"&&Number.isFinite(value),number=value=>finite(value)?String(Math.round(value)):"—";
  const degrees=value=>finite(value)?`${number(value)}°F`:"—";
  const directions=["N","NE","E","SE","S","SW","W","NW"];
  let data=null,busy=false,position={lat:44.9244,lon:-93.414},label="Hopkins · selected location",page=0,watch=null,following=false,active=false,offset=0;
  const now=()=>Date.now()+offset;
  const time=value=>Number.isFinite(Date.parse(value))?clock.format(new Date(value)):"Unknown time";
  function wind(row){
    if(!finite(row?.speedMph))return "—";
    if(row.speedMph<.5)return "Calm";
    return `${finite(row.direction)?directions[Math.round(row.direction/45)%8]:"Variable"} ${number(row.speedMph)} mph`;
  }
  function addCell(row,text){const td=document.createElement("td");td.textContent=text;row.append(td);return td;}
  function renderTable(result){
    let rows=result.nearby;
    if(el("scope").value==="all"){
      const local=new Map(result.nearby.map(row=>[row.station,row]));
      rows=(data?.stations||[]).map(row=>local.get(row.station)||({...row,distanceKm:model.distance(position,row),ageMinutes:(now()-Date.parse(row.time))/60000,reason:"Outside local group"})).sort((a,b)=>a.distanceKm-b.distanceKm||a.station.localeCompare(b.station));
    }
    const term=el("search").value.toLowerCase().trim();
    rows=rows.filter(row=>[row.station,row.name,row.network,row.state].join(" ").toLowerCase().includes(term));
    const pages=Math.max(1,Math.ceil(rows.length/50));page=Math.min(page,pages-1);
    el("stations").replaceChildren();
    for(const station of rows.slice(page*50,page*50+50)){
      const tr=document.createElement("tr");if(station.used&&result.available)tr.className="conditions-contributor";
      const name=addCell(tr,`${station.name||station.station} · ${station.station}`),small=document.createElement("small");small.textContent=`${station.network||"Other"} · ${station.state||""}`;name.append(small);
      addCell(tr,`${(station.distanceKm*.621371).toFixed(1)} mi`);addCell(tr,time(station.time));
      addCell(tr,finite(station.ageMinutes)&&station.ageMinutes>=0?`${Math.floor(station.ageMinutes)} min`:"Invalid time");
      addCell(tr,degrees(station.tempF));addCell(tr,degrees(station.dewpointF));addCell(tr,wind(station.wind));
      addCell(tr,station.used&&!result.available?"Estimate withheld":station.reason||"Comparison");el("stations").append(tr);
    }
    if(!rows.length){const tr=document.createElement("tr"),td=addCell(tr,"No available stations match this selection.");td.colSpan=8;el("stations").append(tr);}
    el("station-count").textContent=`${rows.length} matching stations · ${data?.stations?.length||0} in the public MN/WI inventory · actual observation times shown`;
    el("page").textContent=`${page+1} / ${pages}`;el("prev").disabled=page===0;el("next").disabled=page>=pages-1;
  }
  function render(){
    el("location").textContent=label;
    const sun=window.WeatherSun?.elevation(new Date(now()),position.lat,position.lon);el("sun").textContent=finite(sun)?`${sun.toFixed(1)}°`:"—";
    if(!data)return;
    const result=model.estimate(data.stations||[],position,now());
    const collectorAge=(now()-Date.parse(data.checkedAt))/60000;
    if(!finite(collectorAge)||collectorAge>6){result.available=false;result.reason="Background collection has not refreshed recently. Estimate withheld; station readings remain below.";}
    el("temp").textContent=result.available?degrees(result.tempF):"—";
    el("dew").textContent=result.available?degrees(result.dewpointF):"—";
    el("wind").textContent=result.available?wind(result.wind):"—";
    el("status").textContent=result.available?`Experimental local estimate · ${result.used.length} independent reference sites · ${result.oldestAge>10?"Source delayed: ":""}readings ${Math.floor(result.newestAge)}–${Math.floor(result.oldestAge)} minutes old${data._savedCopy?" · saved inventory while refreshing":""}.`:result.reason;
    el("status").className=result.available&&result.oldestAge<=10?"conditions-status-ok":"notice";
    el("observed").textContent=result.available?`Observed ${time(result.oldestAt)}${result.newestAt!==result.oldestAt?" through "+time(result.newestAt):""} · contributing stations within ${(result.furthestKm*.621371).toFixed(1)} miles · temperature spread ${result.spreadF.toFixed(1)}°F (not an error bound).`:"Nearby individual observations are shown below; no temperature is invented when coverage is insufficient.";
    el("checked").textContent=`Collector checked ${time(data.checkedAt)} · checks every 2 minutes${data.sourceFailures?.length?` · ${data.sourceFailures.length} source requests failed; retained readings keep their original times`:""}.`;
    renderTable(result);
  }
  function accept(value){data=value;if(value.serverTime&&!value._savedCopy)offset=Date.parse(value.serverTime)-Date.now();render();}
  async function load(force=false){
    if(busy)return;busy=true;el("refresh").disabled=true;
    try{accept(await window.WeatherPrepared.read(endpoint,{force}));}
    catch(error){el("status").textContent=error.message;el("status").className="notice";if(data)render();}
    finally{busy=false;el("refresh").disabled=false;}
  }
  function clearWatch(){if(watch!==null)navigator.geolocation?.clearWatch(watch);watch=null;}
  function stop(){clearWatch();following=false;el("stop").hidden=true;el("locate").disabled=false;}
  function startWatch(){
    if(!following||!active||document.hidden||watch!==null)return;
    watch=navigator.geolocation.watchPosition(fix=>{
      position={lat:fix.coords.latitude,lon:fix.coords.longitude};label="Your device location";page=0;
      el("location-status").textContent=`Following while this page is visible · reported position accuracy ±${Math.round(fix.coords.accuracy)} m · coordinates stay in this browser.`;
      render();
    },error=>{stop();el("location-status").textContent=error.code===1?"Location permission was not granted. Your selected location remains in use.":"Could not obtain your location. Your selected location remains in use.";},
    {enableHighAccuracy:true,maximumAge:30000,timeout:20000});
  }
  el("locate").addEventListener("click",()=>{
    if(!navigator.geolocation){el("location-status").textContent="This browser does not provide device location. Choose a place or enter coordinates.";return;}
    following=true;el("stop").hidden=false;el("locate").disabled=true;el("location-status").textContent="Waiting for location permission and a position…";startWatch();
  });
  el("stop").addEventListener("click",()=>{stop();label="Last device location · fixed";el("location-status").textContent="Location following stopped. The last position stays selected on this page.";render();});
  el("place").addEventListener("change",()=>{stop();const [lat,lon]=el("place").value.split(",").map(Number);position={lat,lon};label=`${el("place").selectedOptions[0].textContent} · selected location`;page=0;el("location-status").textContent="Fixed selected location. Device location is not being used.";render();});
  el("coordinates").addEventListener("submit",event=>{
    event.preventDefault();if(!el("lat").value.trim()||!el("lon").value.trim())return;
    const lat=Number(el("lat").value),lon=Number(el("lon").value);if(!finite(lat)||!finite(lon)||Math.abs(lat)>90||Math.abs(lon)>180)return;
    stop();position={lat,lon};label=`${lat.toFixed(4)}, ${lon.toFixed(4)} · selected location`;page=0;el("location-status").textContent="Fixed coordinates. They stay in this browser.";render();
  });
  el("refresh").addEventListener("click",()=>load(true));
  for(const id of ["scope","search"])el(id).addEventListener(id==="search"?"input":"change",()=>{page=0;render();});
  el("prev").addEventListener("click",()=>{page=Math.max(0,page-1);render();});el("next").addEventListener("click",()=>{page++;render();});
  window.WeatherPrepared.subscribe(endpoint,accept);
  setInterval(()=>{if(active&&!document.hidden)load(true);},60000);
  setInterval(()=>{if(active&&!document.hidden)render();},10000);
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden){clearWatch();if(following)el("location-status").textContent="Location following paused while the page is hidden.";}
    else if(active){startWatch();load(true);}
  });
  window.addEventListener("pagehide",clearWatch);
  return {select(id){active=id==="conditions";if(active){render();startWatch();load();}else{clearWatch();if(following)el("location-status").textContent="Location following paused while another weather tab is selected.";}}};
})();
