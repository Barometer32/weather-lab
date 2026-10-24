"use strict";
// Separate weather and cloud station models share the prepared hourly reports.
window.WeatherStationModel = (() => {
  const scale=.82,width=88,height=52,cx=43,cy=26;
  const rounded=v=>v==null?"—":String(Math.round(v));
  const windMph=w=>w?.speedMph??(w?.speedKnots==null?null:w.speedKnots*1.150779);
  const cloudLayers=station=>station.cloudLayers?.length?station.cloudLayers:station.layers||[];
  function firstCloudLayer(station){
    const layers=cloudLayers(station).filter(layer=>["BKN","OVC"].includes(layer.cover));
    // An unreported base prevents asserting that another known layer is lowest.
    if(layers.some(layer=>!Number.isFinite(layer.baseFtAGL)||layer.baseFtAGL<0))return null;
    return layers.sort((a,b)=>a.baseFtAGL-b.baseFtAGL)[0]||null;
  }
  function cloudHeightText(station){
    const layer=firstCloudLayer(station);
    return layer?String(Math.max(1,Math.round(layer.baseFtAGL/1000))):"";
  }
  function skyCode(station){
    if(station.skyCover?.code)return station.skyCover.code;
    const codes=cloudLayers(station).map(layer=>layer.cover);
    return ["VV","OVC","BKN","SCT","FEW","CLR","SKC","NSC","NCD","CAVOK"].find(code=>codes.includes(code))||null;
  }
  function skySymbol(station,x=cx,y=cy){
    const code=skyCode(station),r=4.6;
    const fraction={CLR:0,SKC:0,NSC:0,NCD:0,CAVOK:0,FEW:.25,SCT:.5,BKN:.75,OVC:1}[code];
    let fill="";
    if(fraction===1)fill=`<circle class="sky-fill" cx="${x}" cy="${y}" r="${r}" fill="#111"/>`;
    else if(fraction>0){
      const a=2*Math.PI*fraction,endX=x+r*Math.sin(a),endY=y-r*Math.cos(a);
      fill=`<path class="sky-fill" d="M${x} ${y}L${x} ${y-r}A${r} ${r} 0 ${fraction>.5?1:0} 1 ${endX} ${endY}Z" fill="#111"/>`;
    }else if(code==="VV")fill=`<path class="sky-obscured" d="M${x-2.6} ${y-2.6}l5.2 5.2m-5.2 0l5.2 -5.2" fill="none" stroke="#111" stroke-width="1.4"/>`;
    else if(fraction==null)fill=`<text class="plot-sky-unknown" x="${x}" y="${y+3}" text-anchor="middle">?</text>`;
    return `<g class="plot-sky"><circle cx="${x}" cy="${y}" r="${r+1}" fill="white"/><circle cx="${x}" cy="${y}" r="${r}" fill="white"/>${fill}<circle class="sky-outline" cx="${x}" cy="${y}" r="${r}" fill="none" stroke="#111" stroke-width="1.4"/></g>`;
  }
  function windVector(wind,speed){
    if(speed==null||speed<.5||!Number.isFinite(wind.direction))return "";
    // METAR bearings name the wind source; the arrow points where air is going.
    const rotation=((wind.direction+180)%360+360)%360;
    const shape="M0 -9.5L4.5 -4H1.3V5H-1.3V-4H-4.5Z";
    return `<g class="wind-vector" transform="translate(${cx} ${cy}) rotate(${rotation})"><path class="wind-vector-solid" d="${shape}" fill="#111" stroke="white" stroke-width="1.6" stroke-linejoin="round" paint-order="stroke fill"/></g>`;
  }
  function stationModel(station){
    const wind=station.wind||{},speed=windMph(wind),label=rounded(speed);
    const state=speed==null?"?":speed>=.5&&!Number.isFinite(wind.direction)?(wind.variable?"VRB":"?"):"";
    return `<svg class="metar-plot" width="${width*scale}" height="${height*scale}" viewBox="0 0 ${width} ${height}" aria-hidden="true">${windVector(wind,speed)}<text class="plot-temp" x="29.5" y="22" text-anchor="end">${rounded(station.tempF)}</text><text class="plot-dew" x="29.5" y="40" text-anchor="end">${rounded(station.dewpointF)}</text><text class="plot-speed" x="56.5" y="40" text-anchor="start"${label.length>2?' style="font-size:10px"':""}>${label}</text>${state?`<text class="plot-wind-state" x="${cx}" y="41" text-anchor="middle">${state}</text>`:""}</svg>`;
  }
  const textWidth=(label,small=false)=>label==="—"?13:label.length*(small?6.5:8.5);
  function footprint(station){
    const left=Math.min(29.5-textWidth(rounded(station.tempF)),29.5-textWidth(rounded(station.dewpointF)));
    const label=rounded(windMph(station.wind));
    const right=56.5+textWidth(label,label.length>2);
    return {left:(left-cx-3)*scale,right:(right-cx+3)*scale,top:-18*scale,bottom:19*scale};
  }
  function cloudStationModel(station){
    const label=cloudHeightText(station);
    return `<svg class="metar-plot cloud-plot" width="${48*scale}" height="${34*scale}" viewBox="0 0 48 34" aria-hidden="true">${skySymbol(station,12,19)}${label?`<text class="plot-ceiling" x="21" y="15" text-anchor="start">${label}</text>`:""}</svg>`;
  }
  function cloudFootprint(station){
    const label=cloudHeightText(station);
    return {left:-6.5*scale,right:(label?11+textWidth(label):6.5)*scale,top:(label?-18.5:-6.5)*scale,bottom:6.5*scale};
  }
  return {stationModel,cloudStationModel,cloudFootprint,firstCloudLayer,cloudHeightText,cloudLayers,skyCode,footprint,scale,
    cloudIconSize:[48*scale,34*scale],cloudIconAnchor:[12*scale,19*scale],
    iconSize:[width*scale,height*scale],iconAnchor:[cx*scale,cy*scale]};
})();
