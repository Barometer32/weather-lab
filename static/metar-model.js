"use strict";
// Weather-only station plots; cloud heights use their own map and units.
window.WeatherStationModel = (() => {
  const scale=.82,width=96,height=62,cx=46,cy=30;
  const rounded=v=>v==null?"—":String(Math.round(v));
  const windMph=w=>w?.speedMph??(w?.speedKnots==null?null:w.speedKnots*1.150779);
  const cloudLayers=station=>station.cloudLayers?.length?station.cloudLayers:station.layers||[];
  function firstCloudLayer(station){
    return cloudLayers(station).filter(layer=>["BKN","OVC"].includes(layer.cover)&&
      Number.isFinite(layer.baseFtAGL)&&layer.baseFtAGL>=0)
      .sort((a,b)=>a.baseFtAGL-b.baseFtAGL)[0]||null;
  }
  function cloudHeightText(station){
    const layer=firstCloudLayer(station);
    return layer?String(Math.max(1,Math.round(layer.baseFtAGL/1000))):"";
  }
  function stationModel(station){
    const wind=station.wind||{},speed=windMph(wind),label=rounded(speed);
    let vector="",state="";
    if(speed!=null&&speed>=.5&&wind.direction!=null){
      // METAR directions name where wind comes FROM. The arrow points downwind.
      const rotation=(wind.direction+180)%360,paths='<path d="M0 12V-12M-4.5 -6.5L0 -12L4.5 -6.5"/>';
      vector=`<g class="wind-vector" transform="translate(${cx} ${cy}) rotate(${rotation})" fill="none" stroke-linecap="round" stroke-linejoin="round"><g stroke="white" stroke-width="3.6">${paths}</g><g stroke="#111" stroke-width="1.8">${paths}</g></g>`;
    }else if(speed==null||speed>=.5){
      state=`<text class="plot-wind-state" x="${cx}" y="34" text-anchor="middle">${speed==null?"?":wind.variable?"VRB":"?"}</text>`;
    }
    return `<svg class="metar-plot" width="${width*scale}" height="${height*scale}" viewBox="0 0 ${width} ${height}" aria-hidden="true">${vector}<text class="plot-temp" x="13" y="21" text-anchor="end">${rounded(station.tempF)}</text><text class="plot-dew" x="13" y="44" text-anchor="end">${rounded(station.dewpointF)}</text><text class="plot-speed" x="57" y="53" text-anchor="start"${label.length>2?' style="font-size:10px"':""}>${label}</text>${state}</svg>`;
  }
  function footprint(station){
    const left=Math.min(13-rounded(station.tempF).length*8.5,13-rounded(station.dewpointF).length*8.5);
    const label=rounded(windMph(station.wind)),speedRight=57+label.length*(label.length>2?6.5:8.5);
    return {left:(left-cx-3)*scale,right:(speedRight-cx+3)*scale,top:-31*scale,bottom:31*scale};
  }

  return {stationModel,firstCloudLayer,cloudHeightText,cloudLayers,footprint,scale,
    iconSize:[width*scale,height*scale],iconAnchor:[cx*scale,cy*scale]};
})();
