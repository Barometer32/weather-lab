"use strict";
const $ = id => document.getElementById(id);
const central = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago", hour:"numeric", minute:"2-digit", timeZoneName:"short"});
const fullTime = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago", month:"short", day:"numeric", hour:"numeric", minute:"2-digit", timeZoneName:"short"});
const fmt = v => v == null ? "—" : Math.round(v).toString();
const temp = v => v == null ? "—" : `${fmt(v)}°F`;
const directions = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
function wind(w) {
  if (w.speedMph == null) return "—";
  if (w.speedMph < 0.5) return "Calm";
  const dir = w.direction == null ? "Variable" : directions[Math.round(w.direction / 22.5) % 16];
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
    $("temp-count").textContent = "Routine hourly average";
    $("dewpoint-count").textContent = "Routine hourly average";
    $("wind-count").textContent = "Mean speed · circular direction";
    const qualityLabel = document.createElement("span");
    qualityLabel.textContent = qa.allStationsUsed ? "Combined · 3/3 stations" : `Combined · ${qa.stationsAvailable}/3 reports · QA incomplete`;
    $("qa-status").replaceChildren(qualityDot(qa), qualityLabel);
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
    const stale = document.createElement("span"); stale.textContent = "Refresh failed · readings may be stale";
    $("qa-status").replaceChildren(qualityDot(null, true), stale);
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
  $("sun-time").textContent = `Live · ${central.format(now)}`;
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
let forecastBusy = false;
async function loadForecast() {
  if (forecastBusy) return;
  forecastBusy = true; $("refresh-forecast").disabled = true;
  try {
    const data = await api("/api/forecast"), rows = data.hours;
    const cycle = new Date(data.cycle);
    $("forecast-updated").textContent = `${fullTime.format(new Date(data.windowStart))} through ${fullTime.format(new Date(data.windowEnd))} · updated ${central.format(new Date(data.publishedAt))}`;
    $("forecast-cycle").textContent = `${String(cycle.getUTCHours()).padStart(2,"0")}Z`;
    const parallel = data.sources.RRFS.feed === "parallel";
    $("forecast-feed").textContent = parallel ? "RRFS parallel · HRRR operational" : "HRRR + RRFS operational";
    const dot = document.createElement("span"); dot.className = `qa-dot ${data.stale ? "incomplete" : "passed"}`;
    const label = document.createElement("span"); label.textContent = `${data.stale ? "Older forecast · " : ""}50/50 models · 3/3 sites · ${fullTime.format(cycle)} cycle`;
    $("forecast-quality").replaceChildren(dot, label);
    $("forecast-status").hidden = !data.stale;
    $("forecast-status").textContent = "A newer complete blend has not arrived. The table retains its original forecast times; past rows are marked.";
    const temperatures = rows.map(r=>r.tempF);
    $("forecast-temperature").textContent = `${fmt(Math.min(...temperatures))}–${fmt(Math.max(...temperatures))}°F`;
    $("forecast-rain").textContent = `${data.precipTotalIn.toFixed(2)} in`;
    $("forecast-wind").textContent = `${fmt(Math.max(...rows.map(r=>r.windMph)))} mph`;
    $("forecast-hours").replaceChildren();
    for (const r of rows) {
      const row = document.createElement("tr"), stamp = new Date(r.time), past = stamp.getTime() < Date.now();
      if (past) row.className = "past-forecast";
      const when = document.createElement("td"); when.textContent = fullTime.format(stamp) + (past ? " · past" : ""); row.append(when);
      for (const [key, suffix] of [["tempF","°F"],["dewpointF","°F"],["humidityPct","%"],["windMph"," mph"],["gustMph"," mph"],["precipIn"," in"],["cloudPct","%"],["lowCloudPct","%"],["midCloudPct","%"],["highCloudPct","%"],["surfacePressureHpa"," hPa"]]) {
        const td = document.createElement("td"), value = r[key], sources = r.contributors[key];
        const text = value == null ? "—" : key === "precipIn" ? value.toFixed(3) : fmt(value);
        td.textContent = text + (value == null ? "" : suffix) + (value != null && sources.length === 1 && key.toLowerCase().includes("cloud") ? "*" : "");
        td.title = value == null ? "Unavailable" : `Sources: ${sources.join(" + ")}`;
        row.append(td);
      }
      $("forecast-hours").append(row);
    }
  } catch (error) {
    $("forecast-status").hidden = false;
    $("forecast-status").textContent = error.message + " Any displayed forecast is from the previous successful refresh.";
    $("forecast-quality").textContent = "Forecast refresh unavailable";
  } finally { forecastBusy = false; $("refresh-forecast").disabled = false; }
}

const tabs = ["observations","radar","forecast"];
function selectTab(id) {
  for(const name of tabs) {$(name).hidden=name!==id; $("tab-"+name).setAttribute("aria-selected",String(name===id)); $("tab-"+name).tabIndex=name===id?0:-1;}
  if(id === "radar") { loadRadar(); setTimeout(()=>map && map.invalidateSize(),0); } else stop();
  if(id === "forecast") loadForecast();
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
document.addEventListener("visibilitychange",()=>{if(document.hidden)stop();});
loadObservations();sun();setInterval(sun,30000);
setInterval(()=>{if(!document.hidden)loadObservations();},120000);
setInterval(()=>{if(!document.hidden&&!$("radar").hidden)loadRadar();},300000);

setInterval(()=>{if(!document.hidden&&!$("forecast").hidden)loadForecast();},300000);
