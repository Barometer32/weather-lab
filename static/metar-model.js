"use strict";
// Sky fill represents the METAR category, not an invented exact okta count.
window.WeatherStationModel = (() => {
  const scale=.82,width=88,height=44,cx=34,cy=24,r=5.5;
  const rounded=v=>v==null?"—":String(Math.round(v));
  const windMph=w=>w?.speedMph??(w?.speedKnots==null?null:w.speedKnots*1.150779);
  function ceilingText(station){
    const c=station.ceiling;
    if(!c)return "";
    const label=c.baseFtAGL==null?"?":String(Math.round(c.baseFtAGL/100)).padStart(2,"0");
    return `${c.kind==="verticalVisibility"?"VV ":""}${label}`;
  }
  function cloudText(station){
    const sky=station.skyCover,range=sky?.oktaRange;
    let text=sky?.description||"Cloud cover not reported";
    if(range&&range[1]>0)text+=` · ${range[0]===range[1]?range[0]:range.join("–")}/8 reported cover`;
    const c=station.ceiling;
    if(c)text+=` · ${c.kind==="verticalVisibility"?"Vertical visibility":"Lowest BKN/OVC base"}: ${c.baseFtAGL==null?"unknown":c.baseFtAGL.toLocaleString()+" ft AGL"}`;
    return text;
  }
  function skySymbol(station){
    const sky=station.skyCover,fill=sky?.displayFraction;
    let interior="";
    if(fill===1)interior=`<circle cx="${cx}" cy="${cy}" r="${r}" fill="#111"/>`;
    else if(fill>0&&fill<1){
      const angle=2*Math.PI*fill,x=cx+r*Math.sin(angle),y=cy-r*Math.cos(angle);
      interior=`<path d="M${cx} ${cy} L${cx} ${cy-r} A${r} ${r} 0 ${fill>.5?1:0} 1 ${x.toFixed(3)} ${y.toFixed(3)} Z" fill="#111"/>`;
    }else if(sky?.code==="VV")interior=`<path d="M${cx-3} ${cy-3}L${cx+3} ${cy+3}M${cx+3} ${cy-3}L${cx-3} ${cy+3}" stroke="#111" stroke-width="1.3"/>`;
    else if(fill!==0)interior=`<text class="plot-sky-unknown" x="${cx}" y="${cy+3.3}" text-anchor="middle">?</text>`;
    return `<g class="plot-sky" data-cover="${sky?.code||"unknown"}"><circle cx="${cx}" cy="${cy}" r="${r+1.7}" fill="white"/><circle cx="${cx}" cy="${cy}" r="${r}" fill="white"/>${interior}<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#111" stroke-width="1.4"/></g>`;
  }
  function plotLayout(){
    // Fixed quadrants leave the entire rotating arrow and its halo a central
    // corridor. Wind changes must never move a value during the hourly loop.
    return {temp:13,dew:13,ceiling:55,speed:55};
  }
  function stationModel(station){
    const wind=station.wind||{},speed=windMph(wind),ceiling=ceilingText(station),labels=plotLayout(station);
    let arrow="",state="";
    if(speed!=null&&speed>=.5&&wind.direction!=null){
      const toward=(wind.direction+180)%360,path="M0 -8.5V-14";
      arrow=`<g class="wind-arrow" transform="translate(${cx} ${cy}) rotate(${toward})" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="${path}" stroke="white" stroke-width="5"/><path d="M0 -18L-3.2 -12.8L3.2 -12.8Z" fill="white" stroke="white" stroke-width="1.6"/><path d="${path}" stroke="#111" stroke-width="2.3"/><path class="wind-arrowhead" d="M0 -18L-3.2 -12.8L3.2 -12.8Z" fill="#111"/></g>`;
    }else{
      state=`<text class="plot-wind-state" x="${labels.speed+rounded(speed).length*8.3+4}" y="37">${speed==null?"?":speed<.5?"Calm":wind.variable?"VRB":"?"}</text>`;
      if(speed!=null&&speed<.5)arrow=`<circle class="calm-ring" cx="${cx}" cy="${cy}" r="9" fill="none" stroke="white" stroke-width="3.5"/><circle cx="${cx}" cy="${cy}" r="9" fill="none" stroke="#111" stroke-width="1.1"/>`;
    }
    return `<svg class="metar-plot" width="${width*scale}" height="${height*scale}" viewBox="0 0 ${width} ${height}" aria-hidden="true">${arrow}${skySymbol(station)}<text class="plot-temp" x="${labels.temp}" y="16" text-anchor="end">${rounded(station.tempF)}</text><text class="plot-dew" x="${labels.dew}" y="37" text-anchor="end">${rounded(station.dewpointF)}</text><text class="plot-speed" x="${labels.speed}" y="37">${rounded(speed)}</text>${state}${ceiling?`<text class="plot-ceiling" x="${labels.ceiling}" y="16">${ceiling}</text>`:""}</svg>`;
  }
  function footprint(station){
    const labels=plotLayout(station);
    const speed=windMph(station.wind),wind=station.wind||{};
    const state=speed==null?"?":speed<.5?"Calm":wind.direction==null?(wind.variable?"VRB":"?"):"";
    const windWidth=rounded(speed).length*9+(state?4+state.length*6:0);
    const right=Math.max(labels.speed+windWidth,labels.ceiling+ceilingText(station).length*9);
    const left=Math.min(labels.temp-rounded(station.tempF).length*9,labels.dew-rounded(station.dewpointF).length*9);
    return {left:(left-cx-3)*scale,right:(right-cx+3)*scale,
      top:(3-cy)*scale,bottom:(45-cy)*scale};
  }
  return {stationModel,cloudText,ceilingText,footprint,scale,iconSize:[width*scale,height*scale],iconAnchor:[cx*scale,cy*scale]};
})();

