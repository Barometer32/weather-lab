"use strict";
// Combined hourly station model: sky cover at the site and standard wind barbs.
window.WeatherStationModel = (() => {
  const scale=.82,width=108,height=60,cx=51,cy=30;
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
  function skySymbol(station){
    const code=skyCode(station),r=5.25;
    const fraction={CLR:0,SKC:0,NSC:0,NCD:0,CAVOK:0,FEW:.25,SCT:.5,BKN:.75,OVC:1}[code];
    let fill="";
    if(fraction===1)fill=`<circle class="sky-fill" cx="${cx}" cy="${cy}" r="${r}" fill="#111"/>`;
    else if(fraction>0){
      const a=2*Math.PI*fraction,x=cx+r*Math.sin(a),y=cy-r*Math.cos(a);
      fill=`<path class="sky-fill" d="M${cx} ${cy}L${cx} ${cy-r}A${r} ${r} 0 ${fraction>.5?1:0} 1 ${x} ${y}Z" fill="#111"/>`;
    }else if(code==="VV")fill=`<path class="sky-obscured" d="M${cx-3} ${cy-3}l6 6m-6 0l6 -6" fill="none" stroke="#111" stroke-width="1.4"/>`;
    else if(fraction==null)fill=`<text class="plot-sky-unknown" x="${cx}" y="${cy+3}" text-anchor="middle">?</text>`;
    return `<g class="plot-sky"><circle cx="${cx}" cy="${cy}" r="${r+1}" fill="white"/><circle cx="${cx}" cy="${cy}" r="${r}" fill="white"/>${fill}<circle class="sky-outline" cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#111" stroke-width="1.4"/></g>`;
  }
  function windBarb(wind,speed){
    if(speed==null||speed<.5||!Number.isFinite(wind.direction))return "";
    // Shaft points toward the wind source. Feathers encode knots; text is mph.
    const knots=Math.max(0,Math.round((wind.speedKnots??speed/1.150779)/5)*5);
    const flags=Math.floor(knots/50),full=Math.floor(knots%50/10),half=knots%10>=5;
    // Compress feather spacing for extreme winds without extending into labels.
    const spacing=Math.min(1,14/(flags*4+full*2.5+(half?2.5:0)||1));
    let y=-20,lines='M0 -5.25V-20',pennants="";
    for(let n=0;n<flags;n++){
      pennants+=`<path class="wind-flag" d="M0 ${y}L6 ${y-3*spacing}L0 ${y+4*spacing}Z"/>`;
      y+=4*spacing;
    }
    for(let n=0;n<full;n++){lines+=`M0 ${y}L6 ${y-3*spacing}`;y+=2.5*spacing;}
    if(half){if(!flags&&!full)y+=2.5*spacing;lines+=`M0 ${y}L3 ${y-1.5*spacing}`;}
    const shape=`<path class="wind-shaft" d="${lines}" fill="none"/>${pennants}`;
    return `<g class="wind-barb" transform="translate(${cx} ${cy}) rotate(${wind.direction})" stroke-linecap="round" stroke-linejoin="round"><g class="wind-halo" fill="white" stroke="white" stroke-width="3.6">${shape}</g><g class="wind-ink" fill="#111" stroke="#111" stroke-width="1.6">${shape}</g></g>`;
  }
  function stationModel(station){
    const wind=station.wind||{},speed=windMph(wind),label=rounded(speed),ceiling=cloudHeightText(station);
    const state=speed==null?"?":speed>=.5&&!Number.isFinite(wind.direction)?(wind.variable?"VRB":"?"):"";
    return `<svg class="metar-plot" width="${width*scale}" height="${height*scale}" viewBox="0 0 ${width} 60" aria-hidden="true">${windBarb(wind,speed)}${skySymbol(station)}<text class="plot-temp" x="23" y="22" text-anchor="end">${rounded(station.tempF)}</text><text class="plot-dew" x="23" y="49" text-anchor="end">${rounded(station.dewpointF)}</text><text class="plot-speed" x="79" y="49" text-anchor="start"${label.length>2?' style="font-size:10px"':""}>${label}</text>${ceiling?`<text class="plot-ceiling" x="79" y="22" text-anchor="start">${ceiling}</text>`:""}${state?`<text class="plot-wind-state" x="${cx}" y="44" text-anchor="middle">${state}</text>`:""}</svg>`;
  }
  const textWidth=(label,small=false)=>label==="—"?13:label.length*(small?6.5:8.5);
  function footprint(station){
    const left=Math.min(23-textWidth(rounded(station.tempF)),23-textWidth(rounded(station.dewpointF)));
    const label=rounded(windMph(station.wind));
    const right=79+Math.max(textWidth(label,label.length>2),textWidth(cloudHeightText(station)));
    return {left:(left-cx-3)*scale,right:(right-cx+3)*scale,top:-26*scale,bottom:26*scale};
  }
  function cloudFootprint(station){
    const half=cloudHeightText(station).length*4+.75;
    return {left:-half,right:half,top:-7,bottom:7};
  }
  return {stationModel,cloudFootprint,firstCloudLayer,cloudHeightText,cloudLayers,skyCode,footprint,scale,
    iconSize:[width*scale,height*scale],iconAnchor:[cx*scale,cy*scale]};
})();
