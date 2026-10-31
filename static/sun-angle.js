"use strict";
// Full Julian-century NOAA/Meeus equations; apparent solar-centre elevation.
// https://gml.noaa.gov/grad/solcalc/main.js
window.WeatherSun = (() => {
  const rad=Math.PI/180,latitude=44.925,longitude=-93.463;
  let clockOffset=0;
  function geometricElevation(date, lat=latitude, lon=longitude) {
    const jd=date.getTime()/86400000+2440587.5,t=(jd-2451545)/36525;
    const l=((280.46646+t*(36000.76983+.0003032*t))%360+360)%360;
    const m=357.52911+t*(35999.05029-.0001537*t),e=.016708634-t*(.000042037+.0000001267*t);
    const c=Math.sin(m*rad)*(1.914602-t*(.004817+.000014*t))+Math.sin(2*m*rad)*(.019993-.000101*t)+.000289*Math.sin(3*m*rad);
    const omega=125.04-1934.136*t,lambda=l+c-.00569-.00478*Math.sin(omega*rad);
    const epsilon=23+(26+(21.448-t*(46.815+t*(.00059-.001813*t)))/60)/60+.00256*Math.cos(omega*rad);
    const decl=Math.asin(Math.sin(epsilon*rad)*Math.sin(lambda*rad));
    const y=Math.tan(epsilon*rad/2)**2;
    const eq=4/rad*(y*Math.sin(2*l*rad)-2*e*Math.sin(m*rad)+4*e*y*Math.sin(m*rad)*Math.cos(2*l*rad)
      -.5*y*y*Math.sin(4*l*rad)-1.25*e*e*Math.sin(2*m*rad));
    const hour=date.getUTCHours()+date.getUTCMinutes()/60+date.getUTCSeconds()/3600+date.getUTCMilliseconds()/3600000;
    const solar=((hour*60+eq+4*lon)%1440+1440)%1440,ha=(solar/4-180)*rad;
    return Math.asin(Math.max(-1,Math.min(1,Math.sin(lat*rad)*Math.sin(decl)+Math.cos(lat*rad)*Math.cos(decl)*Math.cos(ha))))/rad;
  }
  function refraction(h) {
    if(h>85)return 0;
    const tangent=Math.tan(h*rad);
    if(h>5)return (58.1/tangent-.07/tangent**3+.000086/tangent**5)/3600;
    if(h>-.575)return (1735+h*(-518.2+h*(103.4+h*(-12.79+h*.711))))/3600;
    return -20.774/tangent/3600;
  }
  function elevation(date, lat=latitude, lon=longitude) {
    const geometric=geometricElevation(date,lat,lon);
    return geometric+refraction(geometric);
  }
  function update(){
    const el=document.getElementById("sun-angle");
    if(el)el.textContent=`${elevation(new Date(Date.now()+clockOffset)).toFixed(1)}°`;
  }
  function sync(serverTime, requestStarted=Date.now()) {
    const server=Date.parse(serverTime),received=Date.now();
    if(Number.isFinite(server))clockOffset=server-(requestStarted+received)/2;
    update();
  }
  update();
  setInterval(update,10000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)update();});
  return {elevation,geometricElevation,refraction,sync,latitude,longitude};
})();
