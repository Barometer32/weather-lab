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
  const response = await fetch(url, {cache:"no-store"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Weather service unavailable.");
  return data;
}
function cell(row, text) { const td = document.createElement("td"); td.textContent = text; row.append(td); }
function qualityDot(qa, stale = false) {
  const dot = document.createElement("span");
  dot.className = `qa-dot ${!stale && qa.allStationsUsed ? "passed" : "incomplete"}`;
  const label = stale ? "Refresh failed; displayed readings may be stale" : qa.allStationsUsed
    ? "Basic QA passed; all 3 stations used"
    : `Basic QA incomplete; ${qa.stationsUsed}/3 stations passed. Temperature ${qa.checks.temperature}/3, dew point ${qa.checks.dewpoint}/3, wind ${qa.checks.wind}/3`;
  dot.title = label; dot.setAttribute("role", "img"); dot.setAttribute("aria-label", label); dot.tabIndex = 0;
  return dot;
}
let observationBusy = false;
async function loadObservations() {
  if (observationBusy) return;
  observationBusy = true; $("refresh-observations").disabled = true;
  try {
    const data = await api("/api/observations"), c = data.current;
    $("updated").textContent = `${fullTime.format(new Date(c.hour))} hourly snapshot`;
    $("temperature").textContent = temp(c.tempF);
    $("dewpoint").textContent = temp(c.dewpointF);
    $("wind").textContent = wind(c.wind);
    const qa = c.qa;
    const status = $("observation-status"); status.hidden = qa.allStationsUsed;
    status.textContent = `Partial hourly average: ${qa.stationsAvailable}/3 reports available. Valid checks: temperature ${qa.checks.temperature}/3, dew point ${qa.checks.dewpoint}/3, wind ${qa.checks.wind}/3. Missing or invalid fields are excluded.`;
    $("history").replaceChildren();
    for (const h of data.history) {
      const row = document.createElement("tr");
      const hourCell = document.createElement("td"), hourLine = document.createElement("span"), time = document.createElement("span");
      hourLine.className = "hour-line"; time.textContent = central.format(new Date(h.hour));
      hourLine.append(qualityDot(h.qa), time); hourCell.append(hourLine); row.append(hourCell);
      cell(row,temp(h.tempF)); cell(row,temp(h.dewpointF)); cell(row,wind(h.wind));
      $("history").append(row);
    }
  } catch (error) {
    for (const dot of $("history").querySelectorAll(".qa-dot")) {
      dot.className = "qa-dot incomplete"; dot.title = "Refresh failed; displayed history may be stale";
      dot.setAttribute("aria-label", dot.title);
    }
    $("observation-status").hidden = false;
    $("observation-status").textContent = `${error.message} Any displayed readings are from the previous successful refresh.`;
  } finally { observationBusy = false; $("refresh-observations").disabled = false; }
}
function sun() {
  if (!window.SunCalc) return;
  const now = new Date(), angle = SunCalc.getPosition(now,44.925,-93.462).altitude * 180 / Math.PI;
  $("sun-angle").textContent = `${angle.toFixed(1)}°`;
}
let map, frames = [], overlays = [], index = 0, timer, radarBusy = false;
function stop() { clearInterval(timer); timer = undefined; $("play").textContent = "Play"; }
function showFrame(n) {
  if (!overlays.length) return;
  index = (n + overlays.length) % overlays.length;
  for (let i = 0; i < overlays.length; i++) overlays[i].setOpacity(i === index ? 1 : 0);
  $("timeline").value = String(index);
  $("timeline").style.setProperty("--progress", `${frames.length > 1 ? index / (frames.length - 1) * 100 : 0}%`);
  $("timeline").setAttribute("aria-valuetext", `${central.format(new Date(frames[index].time))}, scan ${index + 1} of ${frames.length}`);
  $("radar-time").textContent = `${fullTime.format(new Date(frames[index].time))} · ${index + 1}/${frames.length}`;
}
function play() {
  stop(); if (overlays.length < 2) return;
  $("play").textContent = "Pause";
  timer = setInterval(() => showFrame(index+1), Number($("speed").value));
}
function initMap() {
  if (map) return;
  map = L.map("map", {minZoom:5,maxZoom:11}).setView([44.925,-93.462],8);
  map.createPane("radar"); map.getPane("radar").style.zIndex = 350;
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
async function loadRadar() {
  if (radarBusy) return;
  const selectedTime = frames[index]?.time, wasPlaying = Boolean(timer);
  radarBusy = true; stop(); $("refresh-radar").disabled = true;
  for (const id of ["play","previous","next","timeline"]) $(id).disabled = true;
  try {
    initMap();
    $("radar-status").textContent = "Loading available MPX scans…";
    const data = await api("/api/radar");
    $("legend").replaceChildren();
    for (const b of data.bands) {
      const item = document.createElement("div"); item.className="legend-item";
      const swatch = document.createElement("span"); swatch.className="swatch"; swatch.style.backgroundColor=b.color;
      const text = document.createElement("span"), label = document.createElement("span"), range = document.createElement("small"); label.textContent=b.label; range.textContent=b.max>=96?`${b.min}+ dBZ`:`${b.min}–<${b.max} dBZ`;
      text.append(label,range); item.append(swatch,text); $("legend").append(item);
    }
    const loaded = []; let completed = 0, failures = 0;
    // One full raster per scan, shared across all map zoom levels. Bound concurrency.
    const queue = [...data.frames];
    async function worker() {
      while(queue.length && !document.hidden && !$("radar").hidden) {
        const frame = queue.shift();
        try {
          const meta = await api(`/api/radar/${frame.id}/metadata`);
          const image = new Image(); image.src = `/api/radar/${frame.id}.png?style=${encodeURIComponent(data.renderVersion)}`; await image.decode();
          loaded.push({frame,image,bounds:meta.bounds});
        } catch (_) { failures++; }
        completed++; $("radar-status").textContent = `Loading radar ${completed}/${data.frames.length} scans…`;
      }
    }
    await Promise.all([worker(),worker(),worker()]);
    if (!loaded.length) throw new Error("Radar scans could not be loaded. Please try Refresh scans.");
    loaded.sort((a,b)=>a.frame.id.localeCompare(b.frame.id));
    for (const overlay of overlays) map.removeLayer(overlay);
    frames = loaded.map(x=>x.frame);
    overlays = loaded.map(x=>L.imageOverlay(x.image,x.bounds,{opacity:0,pane:"radar",interactive:false}).addTo(map));
    $("timeline").max = String(frames.length-1);
    for (const id of ["play","previous","next","timeline"]) $(id).disabled = frames.length < 2;
    const restored = selectedTime ? frames.findIndex(frame => new Date(frame.time) >= new Date(selectedTime)) : -1;
    showFrame(restored >= 0 ? restored : frames.length-1);
    if (wasPlaying) play();
    const latest = new Date(frames[frames.length-1].time), age = (Date.now()-latest.getTime())/60000;
    const startsLate = (new Date(frames[0].time) - new Date(data.windowStart)) / 60000 > 15;
    const gap = frames.some((frame, i) => i && (new Date(frame.time) - new Date(frames[i-1].time)) / 60000 > 15);
    $("radar-status").textContent =  `Past 2 hours · ${frames.length} scans · ${central.format(new Date(frames[0].time))} to ${central.format(latest)}${failures ? ` · ${failures} scans unavailable` : ""}${startsLate || gap ? " · Some of the two-hour history is unavailable" : ""}${age > 15 ? ` · Latest scan is ${Math.round(age)} minutes old` : ""}`;
  } catch(error) { $("radar-status").textContent=error.message; $("radar-time").textContent=overlays.length?"Previous radar loop · refresh failed":"Radar unavailable";
    if(overlays.length>1) for(const id of ["play","previous","next","timeline"]) $(id).disabled=false;
  } finally {radarBusy=false; $("refresh-radar").disabled=false;}
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
    forecastData = await api("/api/forecast"); forecastError = null; renderForecast();
  } catch (error) {
    forecastError = error.message; renderForecast();
    $("forecast-status").hidden = false;
    $("forecast-status").textContent = `${error.message} Any displayed forecast is from the previous successful refresh.`;
  } finally { forecastBusy = false; $("refresh-forecast").disabled = false; }
}

let satelliteMap, satelliteFrames = [], satelliteOverlays = [], satelliteBoundaries = [], satelliteIndex = 0, satelliteTimer;
let satelliteRequest = 0, satelliteBusy = false, satelliteLoadingProduct;
const satelliteBounds = [[0,0],[900,1600]];
function stopSatellite() { clearInterval(satelliteTimer); satelliteTimer = undefined; $("satellite-play").textContent = "Play"; }
function initSatelliteMap() {
  if (satelliteMap) return;
  satelliteMap = L.map("satellite-map", {crs:L.CRS.Simple,minZoom:-3,maxZoom:2,zoomSnap:0});
  satelliteMap.createPane("satellite-images"); satelliteMap.getPane("satellite-images").style.zIndex = 350;
  satelliteMap.createPane("satellite-boundaries"); satelliteMap.getPane("satellite-boundaries").style.zIndex = 410;
  satelliteMap.getPane("satellite-boundaries").style.pointerEvents = "none";
  satelliteMap.fitBounds(satelliteBounds);
  satelliteMap.on("resize", () => satelliteMap.fitBounds(satelliteBounds, {animate:false}));
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
function playSatellite() {
  stopSatellite(); if (satelliteOverlays.length < 2) return;
  $("satellite-play").textContent = "Pause";
  satelliteTimer = setInterval(() => showSatelliteFrame(satelliteIndex + 1), Number($("satellite-speed").value));
}
async function loadSatellite(force = false) {
  const product = $("satellite-product").value;
  if (satelliteBusy && satelliteLoadingProduct === product && !force) return;
  const request = ++satelliteRequest;
  const wasPlaying = Boolean(satelliteTimer);
  const selectedTime = satelliteFrames[satelliteIndex]?.time;
  const changed = satelliteLoadingProduct != null && satelliteLoadingProduct !== product;
  satelliteLoadingProduct = product; satelliteBusy = true; stopSatellite();
  $("refresh-satellite").disabled = true;
  for (const id of ["play","previous","next","timeline"]) $("satellite-" + id).disabled = true;
  if (changed) {
    for (const overlay of [...satelliteOverlays,...satelliteBoundaries]) satelliteMap.removeLayer(overlay);
    satelliteOverlays = []; satelliteFrames = []; satelliteBoundaries = [];
    $("satellite-time").textContent = "Loading selected product…";
  }
  try {
    initSatelliteMap();
    $("satellite-status").textContent = "Loading local satellite imagery…";
    const data = await api(`/api/satellite/${product}`);
    if (request !== satelliteRequest) return;
    $("satellite-description").textContent = data.description;
    $("satellite-source").href = data.sourceUrl;
    const queue = [...data.frames], loaded = []; let failures = 0, completed = 0;
    async function worker() {
      while (queue.length && request === satelliteRequest && !document.hidden && !$("satellite").hidden) {
        const frame = queue.shift();
        try {
          const image = new Image(); image.src = frame.url; await image.decode();
          if (image.naturalWidth !== data.width || image.naturalHeight !== data.height) throw new Error("Satellite image size changed");
          loaded.push({frame,image});
        } catch (_) { failures++; }
        completed++;
        if (request === satelliteRequest) $("satellite-status").textContent = `Loading satellite ${completed}/${data.frames.length} images…`;
      }
    }
    await Promise.all([worker(),worker()]);
    if (request !== satelliteRequest) return;
    if (!loaded.length) throw new Error("Satellite images could not load. Please try Refresh images.");
    loaded.sort((a,b) => a.frame.time.localeCompare(b.frame.time));
    for (const overlay of [...satelliteOverlays,...satelliteBoundaries]) satelliteMap.removeLayer(overlay);
    satelliteFrames = loaded.map(x => x.frame);
    satelliteOverlays = loaded.map(x => L.imageOverlay(x.image,satelliteBounds,{opacity:0,pane:"satellite-images",interactive:false}).addTo(satelliteMap));
    satelliteBoundaries = data.boundaries.map(url => {
      const overlay = L.imageOverlay(url,satelliteBounds,{pane:"satellite-boundaries",interactive:false}).addTo(satelliteMap);
      overlay.on("error", () => { $("satellite-status").textContent = "Some boundaries could not load. Satellite imagery remains available."; });
      return overlay;
    });
    $("satellite-timeline").max = String(satelliteFrames.length - 1);
    for (const id of ["play","previous","next","timeline"]) $("satellite-" + id).disabled = satelliteFrames.length < 2;
    const restored = selectedTime ? satelliteFrames.findIndex(f => new Date(f.time) >= new Date(selectedTime)) : -1;
    showSatelliteFrame(restored >= 0 ? restored : satelliteFrames.length - 1);
    if (wasPlaying && !document.hidden && !$("satellite").hidden) playSatellite();
    const first = new Date(satelliteFrames[0].time), last = new Date(satelliteFrames.at(-1).time), age = (Date.now() - last.getTime()) / 60000;
    const gaps = satelliteFrames.some((f,i) => i && new Date(f.time) - new Date(satelliteFrames[i-1].time) > 15 * 60000);
    $("satellite-status").textContent = `${data.label} · ${satelliteFrames.length} images · ${central.format(first)} to ${central.format(last)}${failures ? ` · ${failures} images unavailable` : ""}${gaps ? " · Some images are missing" : ""}${age > 20 ? ` · Latest image is ${Math.round(age)} minutes old` : ""}`;
  } catch (error) {
    if (request !== satelliteRequest) return;
    $("satellite-status").textContent = error.message;
    $("satellite-time").textContent = satelliteOverlays.length ? "Previous satellite loop · refresh failed" : "Satellite unavailable";
    if (satelliteOverlays.length > 1) for (const id of ["play","previous","next","timeline"]) $("satellite-" + id).disabled = false;
  } finally {
    if (request === satelliteRequest) { satelliteBusy = false; $("refresh-satellite").disabled = false; }
  }
}

const tabs = ["observations","radar","satellite","forecast"];
function selectTab(id) {
  for(const name of tabs) {$(name).hidden=name!==id; $("tab-"+name).setAttribute("aria-selected",String(name===id)); $("tab-"+name).tabIndex=name===id?0:-1;}
  if(id === "radar") { loadRadar(); setTimeout(()=>map && map.invalidateSize(),0); } else stop();
  if(id === "forecast") loadForecast();
  if(id === "satellite") { loadSatellite(); setTimeout(()=>satelliteMap && satelliteMap.invalidateSize(),0); } else { stopSatellite(); ++satelliteRequest; satelliteBusy = false; $("refresh-satellite").disabled = false; }
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
$("refresh-observations").addEventListener("click",loadObservations);
$("refresh-radar").addEventListener("click",loadRadar);
$("play").addEventListener("click",()=>timer?stop():play());
$("previous").addEventListener("click",()=>{stop();showFrame(index-1);});
$("next").addEventListener("click",()=>{stop();showFrame(index+1);});
$("timeline").addEventListener("input",event=>{stop();showFrame(Number(event.target.value));});
$("timeline").addEventListener("pointerdown",stop);
$("speed").addEventListener("change",()=>{if(timer)play();});
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
document.addEventListener("visibilitychange",()=>{if(document.hidden) { stop(); stopSatellite(); }});
loadObservations();sun();setInterval(sun,30000);
setInterval(()=>{if(!document.hidden)loadObservations();},120000);
setInterval(()=>{if(!document.hidden&&!$("radar").hidden)loadRadar();},300000);

setInterval(()=>{if(!document.hidden&&!$("forecast").hidden)loadForecast();},300000);

setInterval(()=>{if(!document.hidden&&!$("forecast").hidden)renderForecast();},30000);

$("refresh-satellite").addEventListener("click",()=>loadSatellite(true));
$("satellite-product").addEventListener("change",()=>loadSatellite(true));
$("satellite-play").addEventListener("click",()=>satelliteTimer ? stopSatellite() : playSatellite());
$("satellite-previous").addEventListener("click",()=>{stopSatellite();showSatelliteFrame(satelliteIndex-1);});
$("satellite-next").addEventListener("click",()=>{stopSatellite();showSatelliteFrame(satelliteIndex+1);});
$("satellite-timeline").addEventListener("input",event=>{stopSatellite();showSatelliteFrame(Number(event.target.value));});
$("satellite-timeline").addEventListener("pointerdown",stopSatellite);
$("satellite-speed").addEventListener("change",()=>{if(satelliteTimer)playSatellite();});
$("satellite-reset").addEventListener("click",()=>satelliteMap && satelliteMap.fitBounds(satelliteBounds));
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
setInterval(()=>{if(!document.hidden&&!$("satellite").hidden)loadSatellite();},300000);
