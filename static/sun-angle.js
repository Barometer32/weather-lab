"use strict";
// NOAA GML General Solar Position Calculations, UTC and east-positive longitude.
// https://gml.noaa.gov/grad/solcalc/solareqns.PDF
window.WeatherSun = (() => {
  function elevation(date, latitude=44.9244, longitude=-93.414) {
    const rad=Math.PI/180,year=date.getUTCFullYear();
    const day=(Date.UTC(year,date.getUTCMonth(),date.getUTCDate())-Date.UTC(year,0,1))/86400000+1;
    const days=(Date.UTC(year+1,0,1)-Date.UTC(year,0,1))/86400000;
    const hour=date.getUTCHours()+date.getUTCMinutes()/60+date.getUTCSeconds()/3600;
    const gamma=2*Math.PI/days*(day-1+(hour-12)/24);
    const eq=229.18*(.000075+.001868*Math.cos(gamma)-.032077*Math.sin(gamma)-.014615*Math.cos(2*gamma)-.040849*Math.sin(2*gamma));
    const decl=.006918-.399912*Math.cos(gamma)+.070257*Math.sin(gamma)-.006758*Math.cos(2*gamma)+.000907*Math.sin(2*gamma)-.002697*Math.cos(3*gamma)+.00148*Math.sin(3*gamma);
    const solarMinutes=((hour*60+eq+4*longitude)%1440+1440)%1440;
    const ha=(solarMinutes/4-180)*rad,lat=latitude*rad;
    return Math.asin(Math.max(-1,Math.min(1,Math.sin(lat)*Math.sin(decl)+Math.cos(lat)*Math.cos(decl)*Math.cos(ha))))/rad;
  }
  function update(){
    const el=document.getElementById("hopkins-sun-angle");
    if(el)el.textContent=`Hopkins sun elevation: ${elevation(new Date()).toFixed(1)}°`;
  }
  update();
  setInterval(update,60000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)update();});
  return {elevation};
})();
