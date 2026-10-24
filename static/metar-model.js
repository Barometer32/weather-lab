"use strict";
// Weather-only station plots; cloud heights use their own map and units.
window.WeatherStationModel = (() => {
  const scale=.82,width=88,height=56,cx=46,cy=30;
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
      const rotation=(wind.direction+180)%360,shape='M0 -9L3.5 -3H1.1V8H-1.1V-3H-3.5Z';
      vector=`<g class="wind-vector" transform="translate(${cx} ${cy}) rotate(${rotation})" fill="#111" stroke-linejoin="round"><path class="wind-vector-solid" d="${shape}" stroke="white" stroke-width="1.6" paint-order="stroke fill"/></g>`;
    }else if(speed==null||speed>=.5){
      state=`<text class="plot-wind-state" x="${cx}" y="34" text-anchor="middle">${speed==null?"?":wind.variable?"VRB":"?"}</text>`;
    }
    return `<svg class="metar-plot" width="${width*scale}" height="${height*scale}" viewBox="0 0 ${width} ${height}" aria-hidden="true">${vector}<text class="plot-temp" x="30" y="21" text-anchor="end">${rounded(station.tempF)}</text><text class="plot-dew" x="30" y="44" text-anchor="end">${rounded(station.dewpointF)}</text><text class="plot-speed" x="57" y="49" text-anchor="start"${label.length>2?' style="font-size:10px"':""}>${label}</text>${state}</svg>`;
  }
  const textWidth=(label,small=false)=>label==="—"?13:label.length*(small?6.5:8.5);
  function footprint(station){
    const left=Math.min(30-textWidth(rounded(station.tempF)),30-textWidth(rounded(station.dewpointF)));
    const label=rounded(windMph(station.wind)),speedRight=57+textWidth(label,label.length>2);
    return {left:(left-cx-3)*scale,right:(speedRight-cx+3)*scale,top:-25*scale,bottom:22*scale};
  }

  function cloudFootprint(station){
    const half=cloudHeightText(station).length*4+.75;
    return {left:-half,right:half,top:-7,bottom:7};
  }
  return {stationModel,cloudFootprint,firstCloudLayer,cloudHeightText,cloudLayers,footprint,scale,
    iconSize:[width*scale,height*scale],iconAnchor:[cx*scale,cy*scale]};
})();
