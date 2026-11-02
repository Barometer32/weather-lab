"use strict";
// Opt-in device geolocation. No coordinates are sent to the weather server.
window.WeatherRadarLocation = (() => {
  const button=document.getElementById("radar-location"),status=document.getElementById("radar-location-status");
  let map,marker,accuracyRing,watchId=null,enabled=false,active=false,generation=0,centerNext=false;
  try{enabled=localStorage.getItem("weather-radar-location-enabled")==="true";}catch(_){}
  const save=()=>{try{localStorage.setItem("weather-radar-location-enabled",String(enabled));}catch(_){}};
  function note(text=""){status.textContent=text;status.hidden=!text;}
  function label(locating=false){button.textContent=locating?"Locating…":enabled?"Location on":"My location";button.setAttribute("aria-pressed",String(enabled));button.title=enabled?"Hide your location on the radar map":"Show your current location on the radar map";}
  function removeMarkers(){if(marker){map.removeLayer(marker);marker=null;}if(accuracyRing){map.removeLayer(accuracyRing);accuracyRing=null;}}
  function stop(){generation++;if(watchId!==null){navigator.geolocation?.clearWatch(watchId);watchId=null;}removeMarkers();label();}
  function fail(error){enabled=false;save();stop();note(error?.code===1?"Location access was denied. Allow it in your browser settings, then try My location again.":"Your location could not be found. Try My location again, or check your device's location settings.");}
  function start(){
    if(!map||!enabled||!active||document.hidden||watchId!==null)return;
    if(!navigator.geolocation){fail();return;}
    const token=++generation;label(true);note();
    try{
      const id=navigator.geolocation.watchPosition(position=>{
        if(token!==generation||!enabled||!active||document.hidden)return;
        const {latitude:lat,longitude:lon,accuracy}=position.coords||{};
        if(!Number.isFinite(lat)||!Number.isFinite(lon)||Math.abs(lat)>90||Math.abs(lon)>180){fail();return;}
        if(Number.isFinite(position.timestamp)&&Date.now()-position.timestamp>120000){note("Waiting for a fresh location…");return;}
        const coords=[lat,lon],radius=Number.isFinite(accuracy)&&accuracy>=0?accuracy:null;
        const reported=new Date(position.timestamp||Date.now()).toLocaleTimeString([], {hour:"numeric",minute:"2-digit"});
        const text=`Your current location · ${reported}${radius==null?"":` · accuracy about ${radius>=1000?`${(radius/1000).toFixed(1)} km`:`${Math.round(radius)} m`}`}`;
        const popup=document.createElement("span");popup.textContent=text;
        if(!marker){marker=L.circleMarker(coords,{pane:"radar-location",radius:5,color:"#ffffff",weight:1.5,fillColor:"#1976d2",fillOpacity:1}).addTo(map).bindPopup(popup);marker.bindTooltip("Your current location");}
        else marker.setLatLng(coords).setPopupContent(popup);
        if(radius!=null){
          if(!accuracyRing)accuracyRing=L.circle(coords,{pane:"radar-location",radius,color:"#1976d2",weight:1,opacity:.35,fillColor:"#1976d2",fillOpacity:.05,interactive:false}).addTo(map);
          else accuracyRing.setLatLng(coords).setRadius(radius);
          marker.bringToFront?.();
        }else if(accuracyRing){map.removeLayer(accuracyRing);accuracyRing=null;}
        label();note(radius>5000?`Approximate device location: about ${(radius/1000).toFixed(0)} km uncertainty.`:"");
        if(centerNext){centerNext=false;map.panTo(coords,{animate:false});}
      },error=>{if(token===generation&&enabled&&active&&!document.hidden)fail(error);}, {enableHighAccuracy:true,maximumAge:30000,timeout:15000});
      if(token===generation)watchId=id;else navigator.geolocation.clearWatch(id);
    }catch(error){fail(error);}
  }
  button.addEventListener("click",()=>{enabled=!enabled;save();note();if(enabled){centerNext=true;start();}else{centerNext=false;stop();}});
  document.addEventListener("visibilitychange",()=>{if(document.hidden)stop();else start();});
  window.addEventListener("pagehide",stop);
  window.addEventListener("pageshow",start);
  label();
  return {attach(value){if(map)return;map=value;map.createPane("radar-location");map.getPane("radar-location").style.zIndex=650;start();},select(id){active=id==="radar";if(active)start();else stop();}};
})();
