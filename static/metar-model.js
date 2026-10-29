"use strict";
// Compact combined station plots and retained legacy single-variable models.
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
  function windVector(wind,speed,x=cx,y=cy,shape="M0 -9.5L4.5 -4H1.3V5H-1.3V-4H-4.5Z"){
    if(speed==null||speed<.5||!Number.isFinite(wind.direction))return "";
    // METAR bearings name the wind source; the arrow points where air is going.
    const rotation=((wind.direction+180)%360+360)%360;
    return `<g class="wind-vector" transform="translate(${x} ${y}) rotate(${rotation})"><path class="wind-vector-solid" d="${shape}" fill="#111" stroke="white" stroke-width="1.6" stroke-linejoin="round" paint-order="stroke fill"/></g>`;
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
  function cloudPlotLabel(station){
    const height=cloudHeightText(station);
    if(height)return height;
    // Do not imply a known absence of ceiling when cloud data/base is missing.
    if(!skyCode(station)||["BKN","OVC"].includes(skyCode(station))||cloudLayers(station).some(layer=>["BKN","OVC"].includes(layer.cover)))return "?";
    return "";
  }
  function cloudStationModel(station){
    const label=cloudPlotLabel(station);
    return `<svg class="metar-plot cloud-plot" width="${32*scale}" height="${24*scale}" viewBox="0 0 32 24" aria-hidden="true">${label?`<text class="${label==="?"?"plot-cloud-unknown":"plot-ceiling"}" x="16" y="12" text-anchor="middle" dominant-baseline="central">${label}</text>`:'<circle class="cloud-dot" cx="16" cy="12" r="1.9" fill="#111"/>'}</svg>`;
  }
  function cloudFootprint(station){
    const label=cloudPlotLabel(station),half=label?textWidth(label)/2+2.5:3;
    return {left:-half*scale,right:half*scale,top:(label?-9:-3)*scale,bottom:(label?9:3)*scale};
  }
  function singleStationModel(station,mode){
    if(mode==="clouds")return {html:cloudStationModel(station),size:[32*scale,24*scale],anchor:[16*scale,12*scale]};
    if(mode==="wind"){
      const wind=station.wind||{},speed=windMph(wind),state=speed==null?"?":speed>=.5&&!Number.isFinite(wind.direction)?(wind.variable?"VRB":"?"):"";
      const vector=windVector(wind,speed,16,16,"M0 -12L5 -5H1.5V7H-1.5V-5H-5Z");
      const mark=state?`<text class="plot-wind-state" x="16" y="19" text-anchor="middle">${state}</text>`:vector||'<circle cx="16" cy="16" r="1.9" fill="#111"/>';
      return {html:`<svg class="metar-plot" width="${60*scale}" height="${40*scale}" viewBox="0 0 60 40" aria-hidden="true">${mark}<text class="plot-speed" x="29" y="33" text-anchor="start">${rounded(speed)}</text></svg>`,size:[60*scale,40*scale],anchor:[16*scale,16*scale]};
    }
    const value=mode==="dewpoint"?station.dewpointF:station.tempF,cls=mode==="dewpoint"?"plot-dew":"plot-temp";
    return {html:`<svg class="metar-plot" width="${40*scale}" height="${24*scale}" viewBox="0 0 40 24" aria-hidden="true"><text class="${cls}" x="20" y="12" text-anchor="middle" dominant-baseline="central">${rounded(value)}</text></svg>`,size:[40*scale,24*scale],anchor:[20*scale,12*scale]};
  }
  function singleFootprint(station,mode){
    if(mode==="clouds")return cloudFootprint(station);
    if(mode==="wind")return {left:-14*scale,right:(13+textWidth(rounded(windMph(station.wind)))+2)*scale,top:-14*scale,bottom:20*scale};
    const label=rounded(mode==="dewpoint"?station.dewpointF:station.tempF),half=textWidth(label)/2+2;
    return {left:-half*scale,right:half*scale,top:-9*scale,bottom:9*scale};
  }
  const combined={width:88,height:72,x:40,y:36,tempX:-7.5,tempY:-5,dewX:-7.5,dewY:14,ceilingX:8,ceilingY:4};
  const numeric=v=>Number.isFinite(v)?String(Math.round(v)):"—";
  function combinedWind(wind={}){
    wind=wind||{};
    const mph=windMph(wind),speed=Number.isFinite(mph)&&mph>=0?mph:null;
    const knots=Number.isFinite(wind.speedKnots)&&wind.speedKnots>=0?wind.speedKnots:speed==null?null:speed/1.150779;
    if(knots==null)return {kind:"unknown",speed,state:"?",points:[]};
    if(knots===0)return {kind:"calm",speed,points:[]};
    if(!Number.isFinite(wind.direction))return {kind:"unknown",speed,state:wind.variable?"VRB":"?",points:[]};
    const roundedKnots=5*Math.round(knots/5);
    if(roundedKnots===0)return {kind:"calm",speed,roundedKnots,points:[]};
    const flags=Math.floor(roundedKnots/50),full=Math.floor((roundedKnots%50)/10),half=roundedKnots%10>=5;
    const length=Math.max(28,6+flags*8+full*5+(half?5:0));
    const lines=[[[0,-5.9],[0,-length]]],pennants=[];
    let y=-length;
    for(let i=0;i<flags;i++){pennants.push([[0,y],[9.5,y-4.8],[0,y+6]]);y+=8;}
    for(let i=0;i<full;i++){lines.push([[0,y],[9.5,y-4.8]]);y+=5;}
    if(half){if(!flags&&!full)y+=5;lines.push([[0,y],[4.75,y-2.4]]);}
    // A conventional meteorological barb points FROM the reported bearing.
    const rotation=((wind.direction%360)+360)%360,a=rotation*Math.PI/180;
    const points=[...lines.flat(),...pennants.flat()].map(([x,y])=>[x*Math.cos(a)-y*Math.sin(a),x*Math.sin(a)+y*Math.cos(a)]);
    return {kind:"barb",speed,roundedKnots,rotation,lines,pennants,points};
  }
  function combinedBarb(wind){
    if(wind.kind==="calm")return `<circle class="wind-calm" cx="${combined.x}" cy="${combined.y}" r="7.2" fill="none" stroke="#111" stroke-width="1.3"/>`;
    if(wind.kind!=="barb")return "";
    const path=wind.lines.map(([a,b])=>`M${a[0]} ${a[1]}L${b[0]} ${b[1]}`).join("");
    const flags=wind.pennants.map(points=>`<polygon class="wind-flag" points="${points.map(p=>p.join(",")).join(" ")}" fill="#111" stroke="white" stroke-width="1.2" paint-order="stroke fill"/>`).join("");
    return `<g class="wind-barb" data-knots="${wind.roundedKnots}" transform="translate(${combined.x} ${combined.y}) rotate(${wind.rotation})"><path class="wind-barb-halo" d="${path}" fill="none" stroke="white" stroke-width="3.3" stroke-linecap="round" stroke-linejoin="round"/><path class="wind-shaft" d="${path}" fill="none" stroke="#111" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>${flags}</g>`;
  }
  function combinedStationModel(station){
    const w=combinedWind(station.wind),c=combined,ceiling=cloudPlotLabel(station);
    const text=(cls,x,y,value,anchor="start")=>`<text class="${cls}" x="${c.x+x}" y="${c.y+y}" text-anchor="${anchor}">${value}</text>`;
    const state=w.kind==="unknown"?text("plot-wind-state",0,29,w.state,"middle"):"";
    const html=`<svg class="metar-plot combined-station-plot" width="${c.width*scale}" height="${c.height*scale}" viewBox="0 0 ${c.width} ${c.height}" aria-hidden="true">${combinedBarb(w)}${text("plot-temp",c.tempX,c.tempY,numeric(station.tempF),"end")}${text("plot-dew",c.dewX,c.dewY,numeric(station.dewpointF),"end")}${skySymbol(station,c.x,c.y)}${ceiling?text("plot-ceiling",c.ceilingX,c.ceilingY,ceiling):""}${state}</svg>`;
    return {html,size:[c.width*scale,c.height*scale],anchor:[c.x*scale,c.y*scale]};
  }
  function combinedFootprint(station){
    const c=combined,w=combinedWind(station.wind),ceiling=cloudPlotLabel(station);
    let left=-8.5,right=8.5,top=-8.5,bottom=8.5;
    function include(x,y,width,anchor){
      const start=anchor==="end"?x-width:anchor==="middle"?x-width/2:x;
      left=Math.min(left,start-2);right=Math.max(right,start+width+2);
      top=Math.min(top,y-13);bottom=Math.max(bottom,y+3);
    }
    include(c.tempX,c.tempY,textWidth(numeric(station.tempF)),"end");
    include(c.dewX,c.dewY,textWidth(numeric(station.dewpointF)),"end");
    if(ceiling)include(c.ceilingX,c.ceilingY,textWidth(ceiling),"start");
    if(w.kind==="unknown")include(0,29,textWidth(w.state,true),"middle");
    for(const [x,y] of w.points){left=Math.min(left,x-2);right=Math.max(right,x+2);top=Math.min(top,y-2);bottom=Math.max(bottom,y+2);}
    return {left:left*scale,right:right*scale,top:top*scale,bottom:bottom*scale};
  }
  return {combinedStationModel,combinedFootprint,combinedWind,stationModel,cloudStationModel,singleStationModel,singleFootprint,cloudPlotLabel,cloudFootprint,firstCloudLayer,cloudHeightText,cloudLayers,skyCode,footprint,scale,
    cloudIconSize:[32*scale,24*scale],cloudIconAnchor:[16*scale,12*scale],
    iconSize:[width*scale,height*scale],iconAnchor:[cx*scale,cy*scale]};
})();
