"use strict";
// Weather-only station plots; cloud heights use their own map and units.
window.WeatherStationModel = (() => {
  const scale=.82,width=86,height=62,cx=46,cy=30;
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
    let barb="",state="";
    if(speed!=null&&speed>=.5&&wind.direction!=null){
      const knots=wind.speedKnots??speed/1.150779,k=5*Math.round(knots/5);
      const flags=Math.floor(k/50),full=Math.floor((k%50)/10),half=k%10>=5;
      const compression=Math.min(1,14/Math.max(1,flags*5+full*3+(half?3:0)));
      let y=-28,parts=['<path d="M0 -12.5V-28"/>'];
      for(let i=0;i<flags;i++){parts.push(`<path class="wind-flag" d="M0 ${y}L8 ${y+5*compression}L0 ${y+5*compression}Z"/>`);y+=5*compression;}
      for(let i=0;i<full;i++){parts.push(`<path d="M0 ${y}L7 ${y+3}"/>`);y+=3*compression;}
      if(half)parts.push(`<path d="M0 ${y}L3.5 ${y+1.5}"/>`);
      const paths=parts.join("");
      barb=`<g class="wind-barb" transform="translate(${cx} ${cy}) rotate(${wind.direction})" fill="none" stroke-linecap="round" stroke-linejoin="round"><g stroke="white" stroke-width="3">${paths}</g><g stroke="#111" stroke-width="1.6">${paths.replaceAll('class="wind-flag"','class="wind-flag" fill="#111"')}</g></g>`;
    }else if(speed==null||speed>=.5){
      state=`<text class="plot-wind-state" x="${cx}" y="55" text-anchor="middle">${speed==null?"?":wind.variable?"VRB":"?"}</text>`;
    }
    return `<svg class="metar-plot" width="${width*scale}" height="${height*scale}" viewBox="0 0 ${width} ${height}" aria-hidden="true">${barb}<circle class="wind-speed-circle" cx="${cx}" cy="${cy}" r="12.3" fill="white" stroke="#111" stroke-width="1.2"/><text class="plot-temp" x="13" y="21" text-anchor="end">${rounded(station.tempF)}</text><text class="plot-dew" x="13" y="44" text-anchor="end">${rounded(station.dewpointF)}</text><text class="plot-speed" x="${cx}" y="34.5" text-anchor="middle"${label.length>2?' style="font-size:10px"':""}>${label}</text>${state}</svg>`;
  }
  function footprint(station){
    const left=Math.min(13-rounded(station.tempF).length*8.5,13-rounded(station.dewpointF).length*8.5);
    return {left:(left-cx-3)*scale,right:31*scale,top:-31*scale,bottom:31*scale};
  }
  return {stationModel,firstCloudLayer,cloudHeightText,cloudLayers,footprint,scale,
    iconSize:[width*scale,height*scale],iconAnchor:[cx*scale,cy*scale]};
})();
