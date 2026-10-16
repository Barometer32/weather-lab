"use strict";
// Sky fill represents the METAR category, not an invented exact okta count.
window.WeatherStationModel = (() => {
  const scale=.82,width=96,height=46,cx=34,cy=24,r=5.5;
  const rounded=v=>v==null?"—":String(Math.round(v));
  const windMph=w=>w?.speedMph??(w?.speedKnots==null?null:w.speedKnots*1.150779);
  function ceilingText(station){
    const c=station.ceiling;
    if(!c)return "";
    const label=c.baseFtAGL==null?"?":`${Number((c.baseFtAGL/1000).toFixed(1))}k`;
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
  function stationModel(station){
    const wind=station.wind||{},speed=windMph(wind),ceiling=ceilingText(station);
    let arrow="",state="";
    if(speed!=null&&speed>=.5&&wind.direction!=null){
      const toward=(wind.direction+180)%360,path="M0 -8.5V-16M-2.5 -12L0 -16L2.5 -12";
      arrow=`<g class="wind-arrow" transform="translate(${cx} ${cy}) rotate(${toward})" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="${path}" stroke="white" stroke-width="4.5"/><path d="${path}" stroke="#111" stroke-width="1.7"/></g>`;
    }else{
      state=`<text class="plot-wind-state" x="${50+rounded(speed).length*7.2+4}" y="39">${speed==null?"?":speed<.5?"Calm":wind.variable?"VRB":"?"}</text>`;
      if(speed!=null&&speed<.5)arrow=`<circle class="calm-ring" cx="${cx}" cy="${cy}" r="9" fill="none" stroke="white" stroke-width="3.5"/><circle cx="${cx}" cy="${cy}" r="9" fill="none" stroke="#111" stroke-width="1.1"/>`;
    }
    return `<svg class="metar-plot" width="${width*scale}" height="${height*scale}" viewBox="0 0 ${width} ${height}" aria-hidden="true">${arrow}${skySymbol(station)}<text class="plot-temp" x="18" y="16" text-anchor="end">${rounded(station.tempF)}</text><text class="plot-dew" x="18" y="39" text-anchor="end">${rounded(station.dewpointF)}</text><text class="plot-speed" x="50" y="39">${rounded(speed)}</text>${state}${ceiling?`<text class="plot-ceiling" x="50" y="16">${ceiling}</text>`:""}</svg>`;
  }
  function footprint(station){
    const digits=Math.max(rounded(station.tempF).length,rounded(station.dewpointF).length);
    const speed=windMph(station.wind),wind=station.wind||{};
    const state=speed==null?"?":speed<.5?"Calm":wind.direction==null?(wind.variable?"VRB":"?"):"";
    const windWidth=rounded(speed).length*9+(state?4+state.length*6:0);
    const right=Math.max(50+windWidth,50+ceilingText(station).length*7);
    return {left:(18-digits*9-cx-4)*scale,right:(right-cx+4)*scale,
      top:-cy*scale,bottom:(46-cy)*scale};
  }
  return {stationModel,cloudText,ceilingText,footprint,scale,iconSize:[width*scale,height*scale],iconAnchor:[cx*scale,cy*scale]};
})();
