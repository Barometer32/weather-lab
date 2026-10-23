"use strict";
// Weather-only station plots; cloud heights use their own map and units.
window.WeatherStationModel = (() => {
  const scale=.82,width=76,height=46,cx=36,cy=24;
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
    let arrow="",state="";
    if(speed!=null&&speed>=.5&&wind.direction!=null){
      const toward=(wind.direction+180)%360,path="M0 -14.5V-17";
      arrow=`<g class="wind-arrow" transform="translate(${cx} ${cy}) rotate(${toward})" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="${path}" stroke="white" stroke-width="5"/><path d="M0 -20L-3.2 -14.8L3.2 -14.8Z" fill="white" stroke="white" stroke-width="1.6"/><path d="${path}" stroke="#111" stroke-width="2.3"/><path class="wind-arrowhead" d="M0 -20L-3.2 -14.8L3.2 -14.8Z" fill="#111"/></g>`;
    }else if(speed==null||speed>=.5){
      state=`<text class="plot-wind-state" x="${cx}" y="43" text-anchor="middle">${speed==null?"?":wind.variable?"VRB":"?"}</text>`;
    }
    // Fixed anchors keep the labels still as wind rotates around its speed.
    return `<svg class="metar-plot" width="${width*scale}" height="${height*scale}" viewBox="0 0 ${width} ${height}" aria-hidden="true">${arrow}<text class="plot-temp" x="13" y="16" text-anchor="end">${rounded(station.tempF)}</text><text class="plot-dew" x="13" y="37" text-anchor="end">${rounded(station.dewpointF)}</text><text class="plot-speed" x="${cx}" y="28.5" text-anchor="middle"${label.length>2?' style="font-size:10px"':""}>${label}</text>${state}</svg>`;
  }
  function footprint(station){
    const left=Math.min(13-rounded(station.tempF).length*9,13-rounded(station.dewpointF).length*9);
    return {left:(left-cx-3)*scale,right:24*scale,top:-23*scale,bottom:23*scale};
  }
  return {stationModel,firstCloudLayer,cloudHeightText,cloudLayers,footprint,scale,
    iconSize:[width*scale,height*scale],iconAnchor:[cx*scale,cy*scale]};
})();
