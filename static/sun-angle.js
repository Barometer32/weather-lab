"use strict";
// Geometric solar elevation at the forecast location, calculated locally.
// The current clock is independent of the selected satellite history frame.
window.WeatherSun = (() => {
  const card=document.getElementById("sun-angle");
  const value=document.getElementById("sun-angle-value");
  const detail=document.getElementById("sun-angle-detail");
  const panel=document.getElementById("satellite");
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric",minute:"2-digit",timeZoneName:"short"});
  function refresh(){
    if(!card||!value||!detail)return;
    try{
      const now=new Date();
      const radians=window.SunCalc.getPosition(now,Number(card.dataset.lat),Number(card.dataset.lon)).altitude;
      if(!Number.isFinite(radians))throw Error("Invalid solar elevation");
      const degrees=Math.round(radians*180/Math.PI*10)/10;
      value.textContent=`${degrees>0?"+":""}${degrees.toFixed(1)}°`;
      const position=degrees>0?"Above the horizon":degrees<0?"Below the horizon":"At the horizon";
      detail.textContent=`${position} · ${card.dataset.location} · ${clock.format(now)}`;
      card.dataset.position=degrees<0?"below":"above";
    }catch{
      value.textContent="—";
      detail.textContent=`Sun angle unavailable · ${card.dataset.location}`;
    }
  }
  refresh();
  setInterval(()=>{if(!document.hidden&&panel&&!panel.hidden)refresh();},60000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden&&panel&&!panel.hidden)refresh();});
  return {refresh};
})();
