"use strict";
// A single saved selection. Device location is read only inside the button click.
window.WeatherLocation = (()=>{
  const key="weather-selected-location-v1",listeners=new Set();
  const fallback={latitude:44.925,longitude:-93.463,label:"Hopkins, MN · default",selected:false};
  const valid=p=>p&&Number.isFinite(p.latitude)&&Number.isFinite(p.longitude)&&Math.abs(p.latitude)<=85&&Math.abs(p.longitude)<=180;
  let chosen=null,cityRequest=0,cityFailed=false;
  try{const saved=JSON.parse(localStorage.getItem(key));if(valid(saved))chosen={...saved,selected:true};}catch(_){}
  if(chosen&&!(typeof chosen.label==="string"&&chosen.label.length<=160&&chosen.label.trim()))delete chosen.label;
  const get=()=>({...chosen||fallback});
  function render(){
    document.getElementById("current-location").textContent=chosen?(chosen.label||`Selected location · ${cityFailed?"city unavailable":"finding city…"}`):fallback.label;
    document.getElementById("reset-location").hidden=!chosen;
  }
  function save(){try{localStorage.setItem(key,JSON.stringify(chosen));}catch(_){} }
  async function resolveCity(){
    if(!chosen||chosen.label)return;
    const selection=chosen,request=++cityRequest;
    cityFailed=false;render();
    try{
      const response=await fetch("/api/location-name",{method:"POST",headers:{"Content-Type":"application/json"},cache:"no-store",body:JSON.stringify({latitude:selection.latitude,longitude:selection.longitude}),signal:AbortSignal.timeout(12000)});
      const result=await response.json();
      if(!response.ok||typeof result.label!=="string"||!result.label.trim()||result.label.length>160)throw Error("City unavailable");
      if(request!==cityRequest||chosen!==selection)return;
      chosen.label=result.label.trim();save();render();
    }catch(_){if(request===cityRequest&&chosen===selection){cityFailed=true;render();}}
  }
  function notify(){render();for(const listener of listeners)listener(get());}
  const button=document.getElementById("use-location"),status=document.getElementById("location-status");
  button.addEventListener("click",()=>{
    if(!navigator.geolocation){status.hidden=false;status.textContent="This browser cannot provide location. The existing location is retained.";return;}
    button.disabled=true;status.hidden=false;status.textContent="Finding your location…";
    navigator.geolocation.getCurrentPosition(position=>{
      const p={latitude:position.coords.latitude,longitude:position.coords.longitude,accuracy:position.coords.accuracy,selectedAt:new Date().toISOString(),selected:true};
      button.disabled=false;
      if(!valid(p)){status.textContent="The browser returned an invalid position. Your existing location is retained.";return;}
      chosen=p;try{localStorage.removeItem("weather-current-last");}catch(_){}save();
      status.textContent=p.accuracy>10000?"Your browser location is approximate; the city name may also be approximate.":"";status.hidden=!status.textContent;
      notify();resolveCity();
    },error=>{
      button.disabled=false;status.hidden=false;
      status.textContent=error.code===1?"Location permission was not granted. Your existing location is retained.":"Location could not be obtained. Your existing location is retained.";
    },{enableHighAccuracy:false,maximumAge:0,timeout:10000});
  });
  document.getElementById("reset-location").addEventListener("click",()=>{
    chosen=null;cityRequest++;cityFailed=false;try{localStorage.removeItem(key);localStorage.removeItem("weather-current-last");}catch(_){}
    status.hidden=true;status.textContent="";notify();
  });
  function radar(map){
    let marker=null;
    function update(p){
      if(!p.selected){if(marker)map.removeLayer(marker);marker=null;return;}
      if(marker){marker.setLatLng([p.latitude,p.longitude]);return;}
      marker=L.circleMarker([p.latitude,p.longitude],{radius:3.5,color:"#fff",weight:1.5,fillColor:"#2166d1",fillOpacity:1,interactive:false,className:"location-dot"}).addTo(map);
    }
    update(get());listeners.add(update);
  }
  render();resolveCity();
  return {get,radar,subscribe(fn){listeners.add(fn);return ()=>listeners.delete(fn);}};
})();
