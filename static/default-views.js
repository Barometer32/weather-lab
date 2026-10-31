"use strict";
// Opening views use the same pixel footprints as the station collision filter.
window.WeatherDefaultViews = (()=>{
  const airports=[{station:"KFCM",lat:44.8272,lon:-93.4571},{station:"KMIC",lat:45.0619,lon:-93.3539},{station:"KMSP",lat:44.8831,lon:-93.2289}];
  const fallbackFootprint={left:-35,right:22,top:-38,bottom:20},radarKey="weather-radar-default-v1";
  const factoryRadar={center:[44.925,-93.462],zoom:8};
  function project(lat,lon,zoom){
    const world=256*2**zoom,sine=Math.sin(Math.max(-85.05112878,Math.min(85.05112878,lat))*Math.PI/180);
    return {x:(lon+180)/360*world,y:(.5-Math.log((1+sine)/(1-sine))/(4*Math.PI))*world};
  }
  function unproject(x,y,zoom){
    const world=256*2**zoom;
    return [Math.atan(Math.sinh(Math.PI*(1-2*y/world)))*180/Math.PI,x/world*360-180];
  }
  function overlap(a,b){return a.left<b.right+2&&a.right>b.left-2&&a.top<b.bottom+2&&a.bottom>b.top-2;}
  function metar(sites,size){
    const focus=airports.map(airport=>{
      const found=sites.find(s=>s.station.station===airport.station);
      return {station:found?.station||airport,f:found?.f||fallbackFootprint};
    });
    for(let zoom=5;zoom<=13;zoom+=.25){
      const boxes=focus.map(({station,f})=>{const p=project(station.lat,station.lon,zoom);return {left:p.x+f.left,right:p.x+f.right,top:p.y+f.top,bottom:p.y+f.bottom};});
      if(boxes.some((a,i)=>boxes.slice(0,i).some(b=>overlap(a,b))))continue;
      const left=Math.min(...boxes.map(b=>b.left)),right=Math.max(...boxes.map(b=>b.right)),top=Math.min(...boxes.map(b=>b.top)),bottom=Math.max(...boxes.map(b=>b.bottom));
      if(right-left>size.x-32||bottom-top>size.y-32)continue;
      return {center:unproject((left+right)/2,(top+bottom)/2,zoom),zoom};
    }
    return {center:[44.945,-93.343],zoom:9};
  }
  function valid(view){return view&&Array.isArray(view.center)&&view.center.length===2&&view.center.every(Number.isFinite)&&Math.abs(view.center[0])<=85&&Math.abs(view.center[1])<=180&&Number.isFinite(view.zoom)&&view.zoom>=5&&view.zoom<=13;}
  function radar(){
    try{const saved=JSON.parse(window.localStorage.getItem(radarKey));if(valid(saved))return saved;}catch(_){}
    return {center:[...factoryRadar.center],zoom:factoryRadar.zoom};
  }
  function saveRadar(center,zoom){
    const view={center,zoom};if(!valid(view))return false;
    try{window.localStorage.setItem(radarKey,JSON.stringify(view));return true;}catch(_){return false;}
  }
  return {metar,radar,saveRadar};
})();
