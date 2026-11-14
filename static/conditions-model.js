"use strict";
// Deterministic, inspectable experimental estimate; no trained AI or model fill.
// GPS stays in this browser. The server publishes the same inventory to everyone.
(function(root){
  const finite=value=>typeof value==="number"&&Number.isFinite(value);
  function distance(a,b){
    const rad=Math.PI/180,dLat=(b.lat-a.lat)*rad,dLon=(b.lon-a.lon)*rad;
    const x=Math.sin(dLat/2)**2+Math.cos(a.lat*rad)*Math.cos(b.lat*rad)*Math.sin(dLon/2)**2;
    return 6371*2*Math.asin(Math.sqrt(Math.min(1,Math.max(0,x))));
  }
  function weightedMedian(rows,field){
    const values=rows.filter(row=>finite(field(row))).sort((a,b)=>field(a)-field(b));
    if(values.length<3)return null;
    // Re-cap after missing fields are removed: no single station can hold a
    // majority vote even when it is much nearer than the other references.
    let remaining=1,pending=[...values];const weights=new Map();
    while(pending.length){
      const total=pending.reduce((sum,row)=>sum+row.weight,0);
      const capped=pending.filter(row=>remaining*row.weight/total>.4);
      if(!capped.length){for(const row of pending)weights.set(row,remaining*row.weight/total);break;}
      for(const row of capped){weights.set(row,.4);remaining-=.4;}
      pending=pending.filter(row=>!weights.has(row));
    }
    const total=values.reduce((sum,row)=>sum+weights.get(row),0);let running=0;
    for(let i=0;i<values.length;i++){
      running+=weights.get(values[i]);
      if(Math.abs(running-total/2)<1e-9&&i+1<values.length)return (field(values[i])+field(values[i+1]))/2;
      if(running>=total/2)return field(values[i]);
    }
    return null;
  }
  function estimate(stations,position,now=Date.now()){
    if(!finite(position?.lat)||!finite(position?.lon)||Math.abs(position.lat)>90||Math.abs(position.lon)>180)
      return {available:false,reason:"Choose a valid location.",nearby:[],used:[]};
    let nearby=stations.filter(row=>finite(row.lat)&&finite(row.lon)).map(row=>({...row,
      distanceKm:distance(position,row),ageMinutes:(now-Date.parse(row.time))/60000
    })).filter(row=>row.distanceKm<=40).sort((a,b)=>a.distanceKm-b.distanceKm||String(a.station).localeCompare(String(b.station)));
    // Neither an old reading nor a new collector check is a current measurement.
    const fresh=nearby.filter(row=>row.kind==="reference"&&finite(row.tempF)&&finite(row.ageMinutes)&&row.ageMinutes>=0&&row.ageMinutes<=30);
    const newest=Math.min(...fresh.map(row=>row.ageMinutes));
    const used=[];
    for(const row of fresh){
      if(row.ageMinutes>newest+15)continue;
      // Co-located sensors and duplicate network feeds cannot get two votes.
      if(used.some(other=>distance(other,row)<.2))continue;
      used.push({...row,weight:1/(1+(row.distanceKm/10)**2)});
      if(used.length===8)break;
    }
    const ids=new Set(used.map(row=>row.station));
    nearby=nearby.map(row=>({...row,used:ids.has(row.station),reason:ids.has(row.station)?"Contributing":
      row.kind==="community"?"Community comparison":row.kind!=="reference"?"Network not reviewed":
      !finite(row.tempF)?"Temperature missing/QC":!finite(row.ageMinutes)||row.ageMinutes<0?"Invalid report time":
      row.ageMinutes>30?"Older than 30 min":row.ageMinutes>newest+15?"Outside 15-min group":"Other nearby reference"}));
    if(used.length<3)return {available:false,reason:"Not enough independent, recent reference stations for an estimate (need 3).",nearby,used:[],tempF:null,dewpointF:null,wind:{speedMph:null,direction:null}};
    const tempF=weightedMedian(used,row=>row.tempF),dewpointF=weightedMedian(used,row=>row.dewpointF);
    const speeds=used.filter(row=>finite(row.wind?.speedMph)&&row.wind.speedMph>=0);
    const speedWeight=speeds.reduce((sum,row)=>sum+row.weight,0);
    const speedMph=speeds.length>=3?speeds.reduce((sum,row)=>sum+row.wind.speedMph*row.weight,0)/speedWeight:null;
    const directed=speeds.filter(row=>row.wind.speedMph===0||finite(row.wind.direction));
    let u=0,v=0,amount=0;
    for(const row of directed){
      const angle=(row.wind.direction||0)*Math.PI/180,speed=row.wind.speedMph*row.weight;
      u+=Math.sin(angle)*speed;v+=Math.cos(angle)*speed;amount+=speed;
    }
    const direction=directed.length>=3&&amount>0&&Math.hypot(u,v)/amount>.1?(Math.atan2(u,v)*180/Math.PI+360)%360:null;
    return {available:true,nearby,used,tempF,dewpointF,wind:{speedMph,direction},
      newestAt:new Date(now-Math.min(...used.map(row=>row.ageMinutes))*60000).toISOString(),
      oldestAt:new Date(now-Math.max(...used.map(row=>row.ageMinutes))*60000).toISOString(),
      newestAge:Math.min(...used.map(row=>row.ageMinutes)),oldestAge:Math.max(...used.map(row=>row.ageMinutes)),
      furthestKm:Math.max(...used.map(row=>row.distanceKm)),
      spreadF:Math.max(...used.map(row=>row.tempF))-Math.min(...used.map(row=>row.tempF))};
  }
  const model={distance,weightedMedian,estimate};
  if(typeof module!=="undefined"&&module.exports)module.exports=model;
  else root.WeatherConditionsModel=model;
})(typeof window!=="undefined"?window:globalThis);
