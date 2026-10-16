"use strict";
const $ = id => document.getElementById(id);
const central = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago", hour:"numeric", minute:"2-digit", timeZoneName:"short"});
const fullTime = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago", month:"short", day:"numeric", hour:"numeric", minute:"2-digit", timeZoneName:"short"});
const fmt = v => v == null ? "—" : Math.round(v).toString();
const temp = v => v == null ? "—" : `${fmt(v)}°F`;
const directions = ["N","NE","E","SE","S","SW","W","NW"];
function wind(w) {
  if (w.speedMph == null) return "—";
  if (w.speedMph < 0.5) return "Calm";
  const dir = w.direction == null ? "Variable" : directions[Math.round(w.direction / 45) % 8];
  return `${dir} ${fmt(w.speedMph)} mph`;
}
async function api(url) {
  if(window.WeatherData)return window.WeatherData.json(url,{maxAge:15000});
  const response = await fetch(url, {cache:"no-store"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Weather service unavailable.");
  return data;
}
function cell(row, text) { const td = document.createElement("td"); td.textContent = text; row.append(td); }
let map, nativeLayer, frames = [], index = 0, radarBusy = false, radarRequest = 0;
const radarSite = "KMPX";
let radarPalette = [];
const radarViews = {KMPX:{center:[44.925,-93.462],zoom:8}};
const radarLayers = new Map();
let radarSelection=0, radarShownTime;
const radarPending=new Map(), radarCacheLimit=24;

async function showFrame(n) {
  if (!frames.length) return;
  index = (n + frames.length) % frames.length;
  const frame=frames[index],selection=++radarSelection,request=radarRequest;
  $("timeline").value = String(index);
  $("timeline").style.setProperty("--progress", `${frames.length > 1 ? index / (frames.length - 1) * 100 : 0}%`);
  $("timeline").setAttribute("aria-valuetext", `${central.format(new Date(frame.time))}, scan ${index + 1} of ${frames.length}`);
  $("radar-time").textContent=`Loading ${fullTime.format(new Date(frame.time))} · ${index+1}/${frames.length}…`;
  const key=frame.url;
  try {
    let decoded=radarLayers.get(key);
    if(!decoded){
      let pending=radarPending.get(key);
      if(!pending){
        pending=(async()=>{
          const response=window.WeatherData?await window.WeatherData.asset(frame.url):await fetch(frame.url);if(!response.ok)throw Error("Native scan could not load");
          const result=NativeRadar.decode(await response.arrayBuffer());
          if(result.meta.site!==radarSite||result.meta.id!==frame.id)throw Error("Radar scan mismatch");
          return result;
        })();
        radarPending.set(key,pending);
        pending.finally(()=>radarPending.delete(key)).catch(()=>{});
      }
      decoded=await pending;
    }
    if(selection!==radarSelection||request!==radarRequest)return false;
    radarLayers.delete(key);radarLayers.set(key,decoded);
    while(radarLayers.size>radarCacheLimit)radarLayers.delete(radarLayers.keys().next().value);
    nativeLayer.setFrame(decoded,radarPalette);radarShownTime=frame.time;
    $("radar-time").textContent=`${fullTime.format(new Date(frame.time))} · ${index+1}/${frames.length}`;
    return true;
  }catch(error){
    if(selection===radarSelection&&request===radarRequest){
      $("radar-time").textContent=radarShownTime?`Showing ${fullTime.format(new Date(radarShownTime))} · selected scan unavailable`:"Selected radar scan unavailable";
      $("radar-status").textContent=`${error.message}. Select another scan or refresh.`;
    }
    return false;
  }
}
function initMap() {
  if (map) return;
  map = L.map("map", {minZoom:5,maxZoom:13,zoomSnap:.1,zoomDelta:.1}).setView(radarViews[radarSite].center,radarViews[radarSite].zoom);
  map.createPane("radar"); map.getPane("radar").style.zIndex = 350;
  nativeLayer=NativeRadar.layer().addTo(map);
  if (window.WeatherRadarRoads) window.WeatherRadarRoads.addTo(map).catch(() => {
    $("map-note").hidden = false;
    $("map-note").textContent = "Highway reference could not load. Radar echoes remain available.";
  });
  map.createPane("boundaries"); map.getPane("boundaries").style.zIndex = 410;
  map.getPane("boundaries").style.pointerEvents = "none";

  for (const [layer, opacity] of [["uscounties", 0.35], ["usstates", 0.8]]) {
    const boundaries = L.tileLayer(`https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/${layer}/{z}/{x}/{y}.png`, {
      pane:"boundaries", opacity,
      attribution:'Boundaries: <a href="https://mesonet.agron.iastate.edu/ogc/">Iowa Environmental Mesonet</a>'
    }).addTo(map);
    boundaries.on("tileerror", () => {
      $("map-note").hidden = false;
      $("map-note").textContent = "Some map boundaries could not load. Radar echoes remain available.";
    });
  }

}
function renderRadarLegend(palette) {
  const minimum = 10, maximum = 80;
  $("legend").replaceChildren(); $("legend").className = "legend continuous-legend";
  const bar = document.createElement("div"); bar.className = "reflectivity-gradient";
  bar.style.background = `linear-gradient(to right, ${palette.map(p => `${p.color} ${(p.dbz-minimum)/(maximum-minimum)*100}%`).join(", ")})`;
  const ticks = document.createElement("div"); ticks.className = "reflectivity-ticks";
  for (let dbz=10; dbz<=80; dbz+=10) {
    const tick = document.createElement("span"); tick.textContent = dbz === 80 ? "80+" : String(dbz); ticks.append(tick);
  }
  const label = document.createElement("p"); label.className = "small-note"; label.textContent = "Reflectivity · dBZ";
  $("legend").append(bar,ticks,label);
}
async function applyRadar(data,request,selectedTime,followLatest,saved=false){
    if (request !== radarRequest) return;
    renderRadarLegend(data.palette); radarPalette=data.palette;
    $("radar-eyebrow").textContent=`${data.site} · ${data.elevationDegrees}° BASE REFLECTIVITY`;
    if(!data.frames.length)throw Error("No radar scans are available");
    frames=[...data.frames].sort((a,b)=>a.time.localeCompare(b.time));
    const keep=new Set(frames.map(frame=>frame.url));
    for(const key of radarLayers.keys())if(!keep.has(key))radarLayers.delete(key);
    $("timeline").max=String(frames.length-1);$("timeline").disabled=frames.length<2;
    const restored=!followLatest&&selectedTime?frames.findIndex(frame=>new Date(frame.time)>=new Date(selectedTime)):-1;
    const loaded=await showFrame(restored>=0?restored:frames.length-1);
    if(request!==radarRequest||!loaded)return;
    const latest = new Date(frames.at(-1).time), age = (Date.now()-latest.getTime())/60000;
    const startsLate = (new Date(frames[0].time) - new Date(data.windowStart)) / 60000 > 15;
    const gap = frames.some((frame, i) => i && (new Date(frame.time) - new Date(frames[i-1].time)) / 60000 > 15);
    const unavailable = data.collectionErrors || 0;
    const historyHours=data.historyHours||2;
    $("radar-status").textContent = `${data.site} · Past ${historyHours} hours · ${frames.length} scans · ${central.format(new Date(frames[0].time))} to ${central.format(latest)}${unavailable ? ` · ${unavailable} collection/loading errors` : ""}${startsLate || gap ? " · Some of the ${historyHours}-hour history is unavailable" : ""}${age > 15 ? ` · Latest scan is ${Math.round(age)} minutes old` : ""}${data.historyPending ? " · Earlier scans are filling in" : ""}${data.stale ? " · Background updates delayed" : ""}`;
    if(saved)$("radar-status").textContent+=" · Saved radar; checking for updates…";
}
async function loadRadar() {
  if (radarBusy) return;
  const request = ++radarRequest;
  const selectedTime = frames[index]?.time, followLatest = !frames.length || index === frames.length-1;
  radarBusy = true; $("refresh-radar").disabled = true;
  try {
    initMap();
    $("radar-status").textContent = `Checking latest ${radarSite} scans…`;
    const url=`/api/radar?site=${radarSite}`;
    const data=window.WeatherData?await window.WeatherData.json(url,{maxAge:15000,onCached:cached=>applyRadar(cached,request,selectedTime,followLatest,true)}):await api(url);
    await applyRadar(data,request,selectedTime,followLatest);

  } catch(error) {
    if (request !== radarRequest) return;
    $("radar-status").textContent=error.message; $("radar-time").textContent=radarShownTime?"Previous radar loop · refresh failed":"Radar unavailable";
  } finally {
    if (request === radarRequest) {
      radarBusy=false; $("refresh-radar").disabled=false;
      $("timeline").disabled=frames.length<2;
    }
  }
}
let forecastBusy = false, forecastData, forecastError;
function renderForecast() {
  if (!forecastData) return;
  const data = forecastData;
  const periods = data.periods.filter(p => new Date(p.endTime).getTime() > Date.now());
  $("forecast-updated").textContent = data.updatedAt ? `NWS updated ${fullTime.format(new Date(data.updatedAt))} · Central time` : "Official NWS point forecast · Central time";
  $("forecast-status").hidden = !forecastError && periods.length > 0;
  $("forecast-status").textContent = forecastError ? `${forecastError} Any displayed forecast is from the previous successful refresh.` : "No current forecast periods remain. Please refresh.";
  $("forecast-periods").replaceChildren();
  periods.forEach(period => {
    const row = document.createElement("article"); row.className = "forecast-row";
    const name = document.createElement("h2"); name.textContent = period.name;
    const temperature = document.createElement("div"); temperature.className = "forecast-temperature";
    const label = document.createElement("span"); label.textContent = period.isDaytime ? "High" : "Low";
    const value = document.createElement("strong"); value.textContent = period.temperature == null ? "—" : `${period.temperature}°${period.temperatureUnit || "F"}`;
    temperature.append(label, value);
    const detail = document.createElement("p"); detail.className = "forecast-detail"; detail.textContent = period.detailedForecast;
    row.append(name,temperature,detail); $("forecast-periods").append(row);
  });
}
async function loadForecast() {
  if (forecastBusy) return;
  forecastBusy = true; $("refresh-forecast").disabled = true;
  try {
    forecastData = await api("/api/forecast"); forecastError = forecastData.stale ? "Background forecast updates are delayed." : null; renderForecast();
  } catch (error) {
    forecastError = error.message; renderForecast();
    $("forecast-status").hidden = false;
    $("forecast-status").textContent = `${error.message} Any displayed forecast is from the previous successful refresh.`;
  } finally { forecastBusy = false; $("refresh-forecast").disabled = false; }
}

let satelliteMap, satelliteFrames = [], satelliteOverlays = [], satelliteBoundaries = [], satelliteIndex = 0;
let satelliteRequest = 0, satelliteBusy = false, satelliteLoadingProduct;
const satelliteLayers = new Map();
let satelliteBoundaryKey;
const satelliteBounds = [[0,0],[900,1600]];
function fitSatelliteView() {
  if (!satelliteMap) return;
  if (window.innerWidth <= 600) {
    const size = satelliteMap.getSize();
    // Fill the taller phone viewer with the central part of the native image.
    // The complete original remains available by panning or zooming out.
    satelliteMap.setView([450,800], Math.log2(Math.max(size.x/1600,size.y/900)), {animate:false});
  } else satelliteMap.fitBounds(satelliteBounds, {animate:false});
}
function initSatelliteMap() {
  if (satelliteMap) return;
  satelliteMap = L.map("satellite-map", {crs:L.CRS.Simple,minZoom:-3,maxZoom:2,zoomSnap:0,zoomDelta:.1});
  satelliteMap.createPane("satellite-images"); satelliteMap.getPane("satellite-images").style.zIndex = 350;
  satelliteMap.createPane("satellite-boundaries"); satelliteMap.getPane("satellite-boundaries").style.zIndex = 410;
  satelliteMap.getPane("satellite-boundaries").style.pointerEvents = "none";
  fitSatelliteView();
  satelliteMap.on("resize", fitSatelliteView);
  satelliteMap.attributionControl.addAttribution('NOAA GOES / <a href="https://weather.cod.edu/satrad/">COD NEXLAB</a>');
}
function showSatelliteFrame(n) {
  if (!satelliteOverlays.length) return;
  satelliteIndex = (n + satelliteOverlays.length) % satelliteOverlays.length;
  satelliteOverlays.forEach((overlay,i) => overlay.setOpacity(i === satelliteIndex ? 1 : 0));
  const stamp = fullTime.format(new Date(satelliteFrames[satelliteIndex].time));
  $("satellite-time").textContent = `${stamp} · ${satelliteIndex + 1}/${satelliteFrames.length}`;
  $("satellite-timeline").value = String(satelliteIndex);
  $("satellite-timeline").style.setProperty("--progress", `${satelliteFrames.length > 1 ? satelliteIndex / (satelliteFrames.length - 1) * 100 : 0}%`);
  $("satellite-timeline").setAttribute("aria-valuetext", `${stamp}, image ${satelliteIndex + 1} of ${satelliteFrames.length}`);
}
async function loadSatellite(force = false) {
  const product = $("satellite-product").value;
  if (satelliteBusy && satelliteLoadingProduct === product && !force) return;
  const request = ++satelliteRequest;
  const selectedTime = satelliteFrames[satelliteIndex]?.time, followLatest = !satelliteFrames.length || satelliteIndex === satelliteFrames.length-1;
  const changed = satelliteLoadingProduct != null && satelliteLoadingProduct !== product;
  satelliteLoadingProduct = product; satelliteBusy = true;
  $("refresh-satellite").disabled = true;
  $("satellite-timeline").disabled = true;
  if (changed) {
    for (const overlay of [...satelliteOverlays,...satelliteBoundaries]) satelliteMap.removeLayer(overlay);
    satelliteOverlays = []; satelliteFrames = []; satelliteBoundaries = []; satelliteLayers.clear(); satelliteBoundaryKey = undefined;
    $("satellite-time").textContent = "Loading selected product…";
  }
  const showInitial = !satelliteOverlays.length;
  try {
    initSatelliteMap();
    $("satellite-status").textContent = "Loading local satellite imagery…";
    const data = await api(`/api/satellite/${product}`);
    if (request !== satelliteRequest) return;
    $("satellite-description").textContent = data.description;
    $("satellite-source").href = data.sourceUrl;
    const boundaryKey = JSON.stringify(data.boundaries);
    if (boundaryKey !== satelliteBoundaryKey) {
      for (const overlay of satelliteBoundaries) satelliteMap.removeLayer(overlay);
      satelliteBoundaries = data.boundaries.map(url => {
        const overlay = L.imageOverlay(url,satelliteBounds,{pane:"satellite-boundaries",interactive:false}).addTo(satelliteMap);
        overlay.on("error", () => { $("satellite-status").textContent = "Some boundaries could not load. Satellite imagery remains available."; });
        return overlay;
      });
      satelliteBoundaryKey = boundaryKey;
    }
    const queue = [...data.frames].reverse(), loaded = []; let failures = 0, completed = 0;
    async function worker() {
      while (queue.length && request === satelliteRequest && !document.hidden && !$("satellite").hidden) {
        const frame = queue.shift();
        try {
          let entry = satelliteLayers.get(frame.url);
          if (!entry) {
            const image = new Image(); image.src = frame.url; await image.decode();
            if (request !== satelliteRequest) return;
            if (image.naturalWidth !== data.width || image.naturalHeight !== data.height) throw new Error("Satellite image size changed");
            const overlay = L.imageOverlay(image,satelliteBounds,{opacity:0,pane:"satellite-images",interactive:false}).addTo(satelliteMap);
            entry = {frame,overlay}; satelliteLayers.set(frame.url,entry);
          }
          loaded.push(entry);
          if (showInitial && (!satelliteFrames.length || frame.time > satelliteFrames[satelliteIndex].time)) { satelliteFrames=[entry.frame]; satelliteOverlays=[entry.overlay]; showSatelliteFrame(0); }
        } catch (_) { failures++; }
        completed++;
        if (request === satelliteRequest) $("satellite-status").textContent = `Latest image ready · loading loop ${completed}/${data.frames.length} images…`;
      }
    }
    await Promise.all([worker(),worker()]);
    if (request !== satelliteRequest) return;
    if (!loaded.length) throw new Error("Satellite images could not load. Please try Refresh images.");
    loaded.sort((a,b) => a.frame.time.localeCompare(b.frame.time));
    const keep = new Set(loaded.map(entry=>entry.frame.url));
    for (const [key,entry] of satelliteLayers) if (!keep.has(key)) { satelliteMap.removeLayer(entry.overlay); satelliteLayers.delete(key); }
    satelliteFrames = loaded.map(x => x.frame); satelliteOverlays = loaded.map(x => x.overlay);
    $("satellite-timeline").max = String(satelliteFrames.length - 1);
    $("satellite-timeline").disabled = satelliteFrames.length < 2;
    const restored = !followLatest && !changed && selectedTime ? satelliteFrames.findIndex(f => new Date(f.time) >= new Date(selectedTime)) : -1;
    showSatelliteFrame(restored >= 0 ? restored : satelliteFrames.length - 1);
    const first = new Date(satelliteFrames[0].time), last = new Date(satelliteFrames.at(-1).time), age = (Date.now() - last.getTime()) / 60000;
    const unavailable = failures + (data.unavailableImages || 0);
    const gaps = satelliteFrames.some((f,i) => i && new Date(f.time) - new Date(satelliteFrames[i-1].time) > 15 * 60000);
    $("satellite-status").textContent = `${data.label} · ${satelliteFrames.length} images · ${central.format(first)} to ${central.format(last)}${unavailable ? ` · ${unavailable} images unavailable` : ""}${gaps ? " · Some images are missing" : ""}${age > 20 ? ` · Latest image is ${Math.round(age)} minutes old` : ""}${data.stale ? " · Background updates delayed" : ""}`;
  } catch (error) {
    if (request !== satelliteRequest) return;
    $("satellite-status").textContent = error.message;
    $("satellite-time").textContent = satelliteOverlays.length ? "Previous satellite loop · refresh failed" : "Satellite unavailable";
    $("satellite-timeline").disabled = satelliteOverlays.length < 2;
  } finally {
    if (request === satelliteRequest) { satelliteBusy = false; $("refresh-satellite").disabled = false; }
  }
}

const tabs = ["metar-clouds","maps","ai-forecast","radar","satellite","forecast"];
function selectTab(id) {
  for(const name of tabs) {$(name).hidden=name!==id; $("tab-"+name).setAttribute("aria-selected",String(name===id)); $("tab-"+name).tabIndex=name===id?0:-1;}
  WeatherCloudViews.select(id);
  WeatherMaps.select(id);
  window.WeatherAI?.select(id);
  if(id === "radar") { loadRadar(); setTimeout(()=>map && map.invalidateSize(),0); } else { ++radarRequest; radarBusy=false; $("refresh-radar").disabled=false; }
  if(id === "forecast") loadForecast();
  if(id === "satellite") { loadSatellite(); setTimeout(()=>satelliteMap && satelliteMap.invalidateSize(),0); } else { ++satelliteRequest; satelliteBusy = false; $("refresh-satellite").disabled = false; }
}
for(const id of tabs) {
  $("tab-"+id).addEventListener("click",()=>selectTab(id));
  $("tab-"+id).addEventListener("keydown",event=>{
    if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
    event.preventDefault(); const pos=tabs.indexOf(id);
    const next=event.key==="Home"?0:event.key==="End"?tabs.length-1:(pos+(event.key==="ArrowRight"?1:tabs.length-1))%tabs.length;
    selectTab(tabs[next]); $("tab-"+tabs[next]).focus();
  });
}
$("refresh-forecast").addEventListener("click",loadForecast);
$("refresh-radar").addEventListener("click",loadRadar);
$("timeline").addEventListener("input",event=>showFrame(Number(event.target.value)));
$("fullscreen").addEventListener("click",async()=>{
  const surface = $("radar-surface");
  if (surface.classList.contains("expanded")) {
    surface.classList.remove("expanded"); document.body.classList.remove("radar-expanded");
  } else if (document.fullscreenElement) {
    await document.exitFullscreen();
  } else {
    try { await surface.requestFullscreen(); }
    catch (_) { surface.classList.add("expanded"); document.body.classList.add("radar-expanded"); }
  }
  $("fullscreen").textContent = document.fullscreenElement || surface.classList.contains("expanded") ? "Close" : "Expand";
  $("fullscreen").setAttribute("aria-label", $("fullscreen").textContent === "Close" ? "Close expanded radar" : "Expand radar");
  if(map) setTimeout(()=>map.invalidateSize(),0);
});
document.addEventListener("fullscreenchange",()=>{
  $("fullscreen").textContent = document.fullscreenElement ? "Close" : "Expand";
  $("fullscreen").setAttribute("aria-label", document.fullscreenElement ? "Close expanded radar" : "Expand radar");
  if(map)map.invalidateSize();
});
document.addEventListener("keydown",event=>{
  if (event.key === "Escape" && $("radar-surface").classList.contains("expanded")) {
    $("radar-surface").classList.remove("expanded"); document.body.classList.remove("radar-expanded");
    $("fullscreen").textContent = "Expand"; $("fullscreen").setAttribute("aria-label", "Expand radar");
    if(map)map.invalidateSize();
  }
});
selectTab("metar-clouds");
if(window.WeatherData)window.WeatherData.prime();
setInterval(()=>{if(!document.hidden&&!$("radar").hidden)loadRadar();},30000);

// Read the prepared forecast shortly after each :00/:30 collection, rather
// than starting a drifting half-hour timer when the page opens.
function scheduleForecast(){
  const interval=1800000,offset=30000;
  const now=Date.now(),next=(Math.floor((now-offset)/interval)+1)*interval+offset;
  setTimeout(()=>{
    if(!document.hidden&&!$("forecast").hidden)loadForecast();
    scheduleForecast();
  },next-now);
}
scheduleForecast();

setInterval(()=>{if(!document.hidden&&!$("forecast").hidden)renderForecast();},30000);

$("refresh-satellite").addEventListener("click",()=>loadSatellite(true));
$("satellite-product").addEventListener("change",()=>loadSatellite(true));
$("satellite-timeline").addEventListener("input",event=>showSatelliteFrame(Number(event.target.value)));
$("satellite-reset").addEventListener("click",fitSatelliteView);
$("satellite-fullscreen").addEventListener("click",async()=>{
  const surface = $("satellite-surface");
  if (surface.classList.contains("expanded")) {
    surface.classList.remove("expanded"); document.body.classList.remove("satellite-expanded");
  } else if (document.fullscreenElement) {
    await document.exitFullscreen();
  } else {
    try { await surface.requestFullscreen(); }
    catch (_) { surface.classList.add("expanded"); document.body.classList.add("satellite-expanded"); }
  }
  $("satellite-fullscreen").textContent = document.fullscreenElement || surface.classList.contains("expanded") ? "Close" : "Expand";
  $("satellite-fullscreen").setAttribute("aria-label", $("satellite-fullscreen").textContent === "Close" ? "Close expanded satellite" : "Expand satellite");
  if(satelliteMap) setTimeout(()=>satelliteMap.invalidateSize(),0);
});
document.addEventListener("fullscreenchange",()=>{
  if (!document.fullscreenElement && !$("satellite-surface").classList.contains("expanded")) {
    $("satellite-fullscreen").textContent = "Expand"; $("satellite-fullscreen").setAttribute("aria-label","Expand satellite");
  }
  if(satelliteMap)satelliteMap.invalidateSize();
});
document.addEventListener("keydown",event=>{
  if (event.key === "Escape" && $("satellite-surface").classList.contains("expanded")) {
    $("satellite-surface").classList.remove("expanded"); document.body.classList.remove("satellite-expanded");
    $("satellite-fullscreen").textContent = "Expand"; $("satellite-fullscreen").setAttribute("aria-label","Expand satellite");
    if(satelliteMap)satelliteMap.invalidateSize();
  }
});
setInterval(()=>{if(!document.hidden&&!$("satellite").hidden)loadSatellite();},60000);

document.addEventListener("visibilitychange",()=>{
  if (!document.hidden) {
    if (!$("radar").hidden) loadRadar();
    if (!$("satellite").hidden) loadSatellite();
    if (!$("forecast").hidden) loadForecast();
    if (!$("metar-clouds").hidden) WeatherCloudViews.select("metar-clouds");
  }
});
