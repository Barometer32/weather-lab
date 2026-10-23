"use strict";
window.WeatherCurrentViews = (() => {
const $=id=>document.getElementById(id);
const time=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric",minute:"2-digit",second:"2-digit",timeZoneName:"short"});
const fullTime=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",second:"2-digit",timeZoneName:"short"});
let data=null,busy=false,initialized=false,readError=null;
const temperature=v=>Number.isFinite(v)?`${(Math.round(v*10)/10).toFixed(1)}°F`:"—";
function windText(wind){
 if(!Number.isFinite(wind?.speedMph))return "—";
 if(wind.speedMph<.5)return "Calm";
 const direction=Number.isFinite(wind.direction)?["N","NE","E","SE","S","SW","W","NW"][Math.round(wind.direction/45)%8]:"Variable";
 return `${direction} ${Math.round(wind.speedMph)}`;
}
function render(){
 if(!data)return;
 const c=data.current,latest=data.candidate;
 $("temperature").textContent=temperature(c?.tempF);$("dewpoint").textContent=temperature(c?.dewpointF);
 const wind=c?.wind;
 $("wind").textContent=windText(wind);
 $("wind").title=Number.isFinite(wind?.direction)?`${wind.direction%360}° true`:"";
 $("updated").textContent=c?`Average observation time: ${fullTime.format(new Date(c.observedAt))}`:"Waiting for a local MADIS average…";
 $("station-summary").textContent=c?`${c.stationCount} contributing stations · ${latest?.stations?.length||0} local stations listed · within 10 miles`:`${latest?.stations?.length||0} local stations found · within 10 miles`;
 const status=$("observation-status");
 status.textContent=readError||(!c?"Waiting for at least three aligned usable stations per field…":data.held?"Showing the last complete average while local reports align.":"");
 status.hidden=!status.textContent;
 status.className="notice";
 const body=$("current-stations");body.replaceChildren();
 for(const s of latest?.stations||[]){
   const row=document.createElement("tr");
   const stamp=s.observedAt?time.format(new Date(s.observedAt)):"—";
   row.title=[s.station,s.source,s.name].filter(Boolean).join(" · ");
   const label=s.included?(data.held?"Latest group; average held":(s.includedFields||[]).join(", ")):s.status||"Not included";
   for(const value of [s.displayName||s.name||"Local station",s.network||"MADIS",Number.isFinite(s.distanceMiles)?s.distanceMiles.toFixed(1):"—",stamp,temperature(s.tempF).replace("°F","°"),temperature(s.dewpointF).replace("°F","°"),windText(s.wind),label]){
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
   if(Number.isFinite(Date.parse(data.serverTime))){window.WeatherSun?.sync(data.serverTime,sent);}
   render();
 }catch(error){readError=error.message;if(data)render();else{$("observation-status").textContent=error.message;$("observation-status").className="notice";$("observation-status").hidden=false;}}
 finally{busy=false;$("refresh-observations").disabled=false;}
}
function select(id){
 if(id!=="current")return;
 if(!initialized){
   initialized=true;
   try{data=JSON.parse($("initial-current-data")?.textContent||"null");}catch(_){data=null;}
   if(data){if(data.serverTime){window.WeatherSun?.sync(data.serverTime);}render();}
   if(!data?.checkedAt)load();
 }else load();
}
$("refresh-observations").addEventListener("click",load);
setInterval(()=>{if(!document.hidden&&!$("current").hidden)load();},120000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!$("current").hidden)load();});
return {select};
})();
