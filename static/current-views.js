"use strict";
window.WeatherCurrentViews = (() => {
const $=id=>document.getElementById(id);
const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric",minute:"2-digit",second:"2-digit",timeZoneName:"short"});
const fullTime=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",second:"2-digit",timeZoneName:"short"});
let data=null,busy=false,initialized=false,readError=null,clockOffset=0;
const temperature=v=>Number.isFinite(v)?`${Math.round(v)}°F`:"—";
function render(){
 if(!data)return;
 const c=data.current,latest=data.candidate,now=Date.now()+clockOffset;
 const outOfSync=new Set(latest?.outOfSyncStations||[]);
 const delayed=data.collectorDelayed||(data.checkedAt&&now-Date.parse(data.checkedAt)>300000);
 const held=data.held;
 $("temperature").textContent=temperature(c?.tempF);$("dewpoint").textContent=temperature(c?.dewpointF);
 const wind=c?.wind;
 if(!Number.isFinite(wind?.speedMph))$("wind").textContent="—";
 else if(wind.speedMph<.5)$("wind").textContent="Calm";
 else {
   const direction=Number.isFinite(wind.direction)?["N","NE","E","SE","S","SW","W","NW"][Math.round(wind.direction/45)%8]:"Variable";
   $("wind").textContent=`${direction} · ${Math.round(wind.speedMph)} mph`;
   $("wind").title=Number.isFinite(wind.direction)?`${wind.direction%360}° true`:"Variable wind direction";
 }
 $("updated").textContent=c?`Average observation time: ${fullTime.format(new Date(c.observedAt))}${held?" · held":""}`:"Waiting for a complete aligned three-airport average…";
 const reasons=[];
 if(latest?.missingStations?.length)reasons.push(`missing ${latest.missingStations.join(", ")}`);
 if(latest?.timeSpreadExceeded)reasons.push(`station reports span ${(latest.timestampSpreadSeconds/60).toFixed(1)} minutes; maximum is 15 minutes between newest and oldest`);
 if(latest?.invalidStations?.length)reasons.push(`basic quality check failed: ${latest.invalidStations.join(", ")}`);
 if(data.sourceFailures?.length)reasons.push(`source unavailable: ${data.sourceFailures.join("; ")}`);
 if(delayed)reasons.push("background checks are delayed");
 if(readError)reasons.push(readError);
 const status=$("observation-status");
 status.textContent=(held&&c?"Held — showing the last good complete three-station average. ":!c?"No complete aligned average yet. ":"All 3 airport reports passed basic checks. ")+reasons.join(" · ");
 status.className=held||!c||reasons.length?"notice":"small-note";
 $("current-checked").textContent=data.checkedAt?`Last source check: ${time.format(new Date(data.checkedAt))} · checks every 2 minutes`:"Waiting for the first background source check.";
 const body=$("current-stations");body.replaceChildren();
 for(const s of latest?.stations||[]){
   const row=document.createElement("tr");
   const stamp=s.observedAt?time.format(new Date(s.observedAt)):"—";
   const raw=s.rawMetar||"";row.title=[s.source,raw].filter(Boolean).join(" · ");
   const label=latest.invalidStations?.includes(s.code)?"Failed QA":outOfSync.has(s.code)?"Over 15 min behind newest":s.available?"OK":"Missing";
   for(const value of [s.code,stamp,Number.isFinite(s.tempC)?s.tempC.toFixed(0):"—",Number.isFinite(s.dewpointC)?s.dewpointC.toFixed(0):"—",s.source||"Airport METAR",label]){
     const td=document.createElement("td");td.textContent=value;row.append(td);
   }
   body.append(row);
 }
}
async function load(){
 if(busy)return;busy=true;$("refresh-observations").disabled=true;
 const sent=Date.now();
 try{
   const response=await fetch("/api/observations",{cache:"no-store"}),result=await response.json();
   if(!response.ok)throw Error(result.error||"Observation feed unavailable.");
   data=result;readError=null;
   if(Number.isFinite(Date.parse(data.serverTime))){clockOffset=Date.parse(data.serverTime)-(sent+Date.now())/2;window.WeatherSun?.sync(data.serverTime,sent);}
   render();
 }catch(error){readError=error.message;if(data)render();else{$("observation-status").textContent=error.message;$("observation-status").className="notice";}}
 finally{busy=false;$("refresh-observations").disabled=false;}
}
function select(id){
 if(id!=="current")return;
 if(!initialized){
   initialized=true;
   try{data=JSON.parse($("initial-current-data")?.textContent||"null");}catch(_){data=null;}
   if(data){if(data.serverTime){clockOffset=Date.parse(data.serverTime)-Date.now();window.WeatherSun?.sync(data.serverTime);}render();}
   if(!data?.checkedAt)load();
 }else load();
}
$("refresh-observations").addEventListener("click",load);
setInterval(()=>{if(!document.hidden&&!$("current").hidden)load();},30000);
setInterval(()=>{if(!document.hidden&&!$("current").hidden)render();},10000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!$("current").hidden)load();});
return {select};
})();
