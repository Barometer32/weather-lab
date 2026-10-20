"use strict";
window.WeatherModelViews = (() => {
const $ = id => document.getElementById(id);
const local = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago", hour:"numeric", timeZoneName:"short"});
const runTime = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago", month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
const number = v => Number.isFinite(v) ? String(Math.round(v)) : "—";
const metrics = [
  ["TMP °F", h=>number(h.tempF)],
  ["DPT °F", h=>number(h.dewpointF)],
  ["WDR °", h=>Number.isFinite(h.wind?.direction) ? String(Math.round(h.wind.direction)%360).padStart(3,"0") : "—"],
  ["WSP kt", h=>number(h.wind?.speedKt)],
  ["P01 in", h=>Number.isFinite(h.precipIn) ? (h.precipIn>0&&h.precipIn<.005?"<.01":h.precipIn.toFixed(2)) : "—"],
  ["CLD", h=>h.cloudCategory || "—"],
  ["CIG hft", h=>Number.isFinite(h.ceilingFtAGL) ? String(Math.round(h.ceilingFtAGL/100)) : "—"]
];
let busy=false;
function appendCell(row, tag, value) {
  const node=document.createElement(tag);node.textContent=value;row.append(node);return node;
}
function render(data) {
  const state=data.status?.state || "waiting", status=$("models-status"), working=["probing","collecting"].includes(state);
  let message = working ? (state==="probing"?"Checking the latest complete common model run…":`Preparing model hours: ${data.status.completed} / ${data.status.total} model-hour files processed.`)
    : state==="error"?"The latest collection failed. Any displayed table is the previous complete blend."
    : data.available?"50% HRRR + 50% RRFS · KFCM, KMIC and KMSP equally weighted.":"Waiting for the first background model collection.";
  if(data.stale)message+=" Guidance is delayed; check the run and valid times.";
  status.textContent=message;status.className=data.stale||state==="error"?"notice":"small-note";
  if(!data.available)return;
  $("models-updated").textContent=`Run ${runTime.format(new Date(data.cycleTime))} · ${new Date(data.cycleTime).toISOString().slice(11,13)}Z · forecast hours 02–17`;
  const head=$("models-hours"),body=$("models-rows");head.replaceChildren();body.replaceChildren();
  appendCell(head,"th","Valid time").scope="col";
  for(const hour of data.hours) {
    const cell=appendCell(head,"th",local.format(new Date(hour.validTime)));cell.scope="col";
    cell.title=`F${String(hour.forecastHour).padStart(2,"0")} · ${runTime.format(new Date(hour.validTime))}. P01 covers ${runTime.format(new Date(hour.precipStart))} to ${runTime.format(new Date(hour.precipEnd))}.`;
    const sub=document.createElement("small");sub.textContent=`F${String(hour.forecastHour).padStart(2,"0")}`;cell.append(sub);
  }
  for(const [label,format] of metrics) {
    const row=document.createElement("tr");appendCell(row,"th",label).scope="row";
    for(const hour of data.hours) {
      const cell=appendCell(row,"td",format(hour));
      if(label==="CLD"&&Number.isFinite(hour.cloudPct))cell.title=`Blended total cloud cover: ${Math.round(hour.cloudPct)}%`;
      if(label==="P01 in")cell.title=`Liquid-equivalent precipitation during the hour ending ${runTime.format(new Date(hour.precipEnd))}; not a running total or probability.`;
    }
    body.append(row);
  }
  $("models-table").hidden=false;
}
async function load() {
  if(busy)return;busy=true;$("refresh-models").disabled=true;
  try {
    const response=await fetch("/api/models",{cache:"no-store"}),data=await response.json();
    if(!response.ok)throw Error(data.error||"Model guidance unavailable.");
    render(data);
  } catch(error) {
    $("models-status").textContent=`${error.message} Any displayed table is from the previous successful refresh.`;
    $("models-status").className="notice";
  } finally {busy=false;$("refresh-models").disabled=false;}
}
function select(id){if(id==="models")load();}
$("refresh-models").addEventListener("click",load);
setInterval(()=>{if(!document.hidden&&!$("models").hidden)load();},30000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!$("models").hidden)load();});
return {select};
})();
