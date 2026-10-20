"use strict";
window.WeatherCurrentViews = (() => {
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
function renderObservations(data) {
  const c = data.current;
  $("updated").textContent = `${fullTime.format(new Date(c.hour))} hourly observation`;
  const stale = Boolean(data.stale), warnings=[];
  if(!c.available)warnings.push(`Hourly average unavailable: ${c.missingStations?.length?`waiting for a routine report near :53 from ${c.missingStations.join(", ")}`:"all 3 routine reports must pass temperature, dew point and wind QA"}. Shared collection at :00; hourly history remains below.`);
  if(stale)warnings.push("Background observation checks are delayed; check the displayed observation hour.");
  const status = $("observation-status");status.hidden=warnings.length===0;status.textContent=warnings.join(" ");
  $("history").replaceChildren();
  for (const h of data.history) {
    const row = document.createElement("tr");
    const hourCell = document.createElement("td"), hourLine = document.createElement("span"), time = document.createElement("span");
    hourLine.className = "hour-line"; time.textContent = central.format(new Date(h.hour));
    hourLine.append(qualityDot(h.qa, stale), time); hourCell.append(hourLine); row.append(hourCell);
    cell(row,temp(h.tempF)); cell(row,temp(h.dewpointF)); cell(row,wind(h.wind));
    $("history").append(row);
  }
}
let observationBusy = false;
async function loadObservations() {
  if (observationBusy) return;
  observationBusy = true; $("refresh-observations").disabled = true;
  try {
    const data=await api("/api/observations");
    renderObservations(data);
    const now=new Date(),due=new Date(now);due.setUTCMinutes(0,0,0);
    if(due>now)due.setUTCHours(due.getUTCHours()-1);
    clearTimeout(observationRetry);
    if(waitUntil>Date.now()&&new Date(data.checkedAt)<due)retryPrepared();else waitUntil=0;
  } catch (error) {
    for (const dot of $("history").querySelectorAll(".qa-dot")) {
      dot.className = "qa-dot incomplete"; dot.title = "Refresh failed; displayed history may be stale";
      dot.setAttribute("aria-label", dot.title);
    }
    $("observation-status").hidden = false;
    $("observation-status").textContent = `${error.message} Any displayed readings are from the previous successful refresh.`;
  retryPrepared();
  } finally { observationBusy = false; $("refresh-observations").disabled = false; }
}
let observationTimer, observationRetry, waitUntil=0, initialized=false;
function retryPrepared() {
  clearTimeout(observationRetry);
  if(waitUntil>Date.now())observationRetry=setTimeout(()=>{
    if(!document.hidden&&!$("current").hidden)loadObservations();
  },60000);
}
function scheduleObservations() {
  clearTimeout(observationTimer);
  const now=new Date(),hour=new Date(now);hour.setUTCMinutes(0,0,0);
  const next=[0,1].map(offset=>new Date(hour.getTime()+offset*3600000+30000)).find(t=>t>now);
  observationTimer=setTimeout(()=>{
    if(!document.hidden&&!$("current").hidden){waitUntil=Date.now()+120000;loadObservations();}
    scheduleObservations();
  },next-now);
}
function select(id) {
  if(id!=="current")return;
  if(!initialized){
    initialized=true;
    let initial;
    try{initial=JSON.parse($("initial-current-data")?.textContent||"null");}catch(_){initial=null;}
    if(initial?.current)renderObservations(initial);else{waitUntil=Date.now()+120000;loadObservations();}
  }else{waitUntil=Date.now()+120000;loadObservations();}
  scheduleObservations();
}
$("refresh-observations").addEventListener("click",loadObservations);
return {select};
})();
