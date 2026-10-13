"use strict";
// Shared by the map, its worker, and numerical tests. No DOM dependencies.
(function(root){
  const fields={
    plots:{name:"Station plots",unit:"°F · mph"},
    tempF:{name:"Temperature",unit:"°F",min:-40,max:110,step:5,ticks:[-40,0,32,50,70,90,110]},
    dewpointF:{name:"Dew point",unit:"°F",min:-40,max:110,step:5,ticks:[-40,0,32,50,70,90,110]},
    windMph:{name:"Wind speed + flow",unit:"mph",min:0,max:60,step:5,ticks:[0,10,20,30,40,50,60]},
    gustMph:{name:"Wind gust",unit:"mph",min:0,max:60,step:5,ticks:[0,10,20,30,40,50,60]},
    rh:{name:"Relative humidity",unit:"%",min:0,max:100,step:10,ticks:[0,20,40,60,80,100]},
    spreadF:{name:"Temperature–dew-point spread",unit:"°F",min:0,max:50,step:5,ticks:[0,10,20,30,40,50]}
  };
  const weatherTemp=[[-40,"#59338d"],[0,"#3e61b8"],[32,"#31a7c8"],[50,"#39a776"],[70,"#eed654"],[90,"#eb893e"],[110,"#bb3434"]];
  const colorblind=[[0,"#440154"],[.2,"#414487"],[.4,"#2a788e"],[.6,"#22a884"],[.8,"#7ad151"],[1,"#fde725"]];
  const ramps={wind:[[0,"#d9f1f0"],[10,"#78c3b8"],[20,"#3c9caa"],[30,"#6769b7"],[40,"#bc5899"],[50,"#e18c49"],[60,"#b62d37"]],
    rh:[[0,"#f0e4c3"],[20,"#d4c88b"],[40,"#a4c5a0"],[60,"#63b0ae"],[80,"#3989b1"],[100,"#3b477e"]],
    spread:[[0,"#224e87"],[10,"#4fa5bc"],[20,"#9ec793"],[30,"#e5d475"],[40,"#dc8d48"],[50,"#a64038"]]};
  const allowed=(s,field,quality="passed")=>{
    const q=s.qc?.[field];if(!q?.accepted)return false;
    if(quality==="verified")return ["V","METAR"].includes(q.descriptor);
    if(quality==="madis")return ["C","S","V","METAR"].includes(q.descriptor);
    return ["C","S","V","METAR","LOCAL"].includes(q.descriptor);
  };
  const excluded=new Set(["KCFE","KFCE","KSGS"]);
  function filter(stations,source="all",quality="passed"){
    return stations.filter(s=>!excluded.has(s.station)&&
      (source==="all"||source==="roads"&&["airport","road"].includes(s.kind)||source==="airports"&&s.kind==="airport"||source==="mndot"&&s.network==="MN_RWIS")&&
      ["tempF","dewpointF","windMph","rh","gustMph"].some(k=>Number.isFinite(s[k])&&allowed(s,k,quality)));
  }
  function palette(field,scheme="weather"){
    const f=fields[field]||fields.tempF;
    if(scheme==="colorblind")return colorblind.map(([n,c])=>[f.min+n*(f.max-f.min),c]);
    return field==="tempF"||field==="dewpointF"?weatherTemp:field==="rh"?ramps.rh:field==="spreadF"?ramps.spread:ramps.wind;
  }
  const rgb=c=>[1,3,5].map(i=>parseInt(c.slice(i,i+2),16));
  function color(value,field,scheme="weather"){
    const ramp=palette(field,scheme);let i=0;while(i<ramp.length-2&&value>ramp[i+1][0])i++;
    const [lo,a]=ramp[i],[hi,b]=ramp[i+1],mix=Math.max(0,Math.min(1,(value-lo)/(hi-lo)));
    return rgb(a).map((v,k)=>Math.round(v+(rgb(b)[k]-v)*mix));
  }
  const project=(lat,lon)=>[lon*78.6267,lat*111.195];
  const inverse=p=>[p[1]/111.195,p[0]/78.6267];
  const cross=(o,a,b)=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]);
  function hull(points){
    const p=[...points].sort((a,b)=>a[0]-b[0]||a[1]-b[1]);if(p.length<3)return [];
    const lower=[],upper=[];
    for(const a of p){while(lower.length>=2&&cross(lower.at(-2),lower.at(-1),a)<=0)lower.pop();lower.push(a);}
    for(const a of p.reverse()){while(upper.length>=2&&cross(upper.at(-2),upper.at(-1),a)<=0)upper.pop();upper.push(a);}
    return lower.slice(0,-1).concat(upper.slice(0,-1));
  }
  function inside(point,polygon){
    if(polygon.length<3)return false;
    let result=false;
    for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
      const a=polygon[i],b=polygon[j];
      if((a[1]>point[1])!==(b[1]>point[1])&&point[0]<(b[0]-a[0])*(point[1]-a[1])/(b[1]-a[1])+a[0])result=!result;
    }
    return result;
  }
  function build(stations,field,quality="passed",detail="detail"){
    const vector=field==="windMph";
    const radius=detail==="smooth"?80:45,power=detail==="smooth"?2:3,limit=detail==="smooth"?20:12;
    const points=stations.filter(s=>vector?Number.isFinite(s.uMph)&&Number.isFinite(s.vMph)&&allowed(s,"vector",quality):Number.isFinite(s[field])&&allowed(s,field,quality))
      .map(s=>({xy:project(s.lat,s.lon),value:s[field],u:s.uMph,v:s.vMph,
        weight:(s.kind==="airport"?2:s.kind==="road"?1.2:s.network==="APRSWXNET"?.55:1)*(s.qc?.[vector?"vector":field]?.descriptor==="LOCAL"?.5:1),station:s}));
    // Identical sites do not get multiple votes in the analyzed field.
    const unique=new Map();points.sort((a,b)=>b.weight-a.weight);
    for(const p of points){const key=p.xy.map(n=>Math.round(n*10)).join(":");if(!unique.has(key))unique.set(key,p);}
    const data=[...unique.values()],polygon=hull(data.map(p=>p.xy)),bins=new Map(),binSize=20;
    for(const p of data){const key=p.xy.map(n=>Math.floor(n/binSize)).join(":");if(!bins.has(key))bins.set(key,[]);bins.get(key).push(p);}
    function sample(lat,lon){
      const xy=project(lat,lon);if(!inside(xy,polygon))return null;
      const bx=Math.floor(xy[0]/binSize),by=Math.floor(xy[1]/binSize),span=Math.ceil(radius/binSize)+1,found=[];
      for(let x=bx-span;x<=bx+span;x++)for(let y=by-span;y<=by+span;y++)for(const p of bins.get(x+":"+y)||[]){
        const d=Math.hypot((p.station.lon-lon)*111.195*Math.cos((p.station.lat+lat)*Math.PI/360),(p.station.lat-lat)*111.195);if(d<=radius)found.push({p,d});
      }
      found.sort((a,b)=>a.d-b.d);const nearest=found.slice(0,limit);
      if(nearest.length<3)return null;
      let total=0,value=0,u=0,v=0;
      for(const {p,d} of nearest){const w=p.weight/Math.pow(Math.max(.5,d),power);total+=w;value+=p.value*w;u+=(p.u||0)*w;v+=(p.v||0)*w;}
      u/=total;v/=total;
      return {value:vector?Math.hypot(u,v):value/total,u:vector?u:null,v:vector?v:null,nearestKm:nearest[0].d,support:nearest.length};
    }
    return {sample,count:data.length,radius};
  }
  const mercator=lat=>Math.log(Math.tan(Math.PI/4+lat*Math.PI/360));
  const latitude=y=>(2*Math.atan(Math.exp(y))-Math.PI/2)*180/Math.PI;
  function analyze(message){
    const {bounds,width,height,field,quality,detail,stations}=message;
    const grid=build(stations,field,quality,detail),values=new Float32Array(width*height).fill(NaN),u=new Float32Array(width*height).fill(NaN),v=new Float32Array(width*height).fill(NaN),support=new Uint8Array(width*height);
    const south=mercator(bounds[0][0]),north=mercator(bounds[1][0]);
    const latAt=y=>latitude(north+(south-north)*y/(height-1));
    const lonAt=x=>bounds[0][1]+(bounds[1][1]-bounds[0][1])*x/(width-1);
    for(let y=0;y<height;y++)for(let x=0;x<width;x++){
      const result=grid.sample(latAt(y),lonAt(x)),i=y*width+x;if(!result)continue;
      values[i]=result.value;if(result.u!=null){u[i]=result.u;v[i]=result.v;}support[i]=result.support;
    }
    const contours=[];const f=fields[field];
    // Marching squares in the same Mercator sampling grid as the image.
    for(let level=Math.ceil(f.min/f.step)*f.step;level<=f.max;level+=f.step){
      const segments=[];
      for(let y=0;y<height-1;y++)for(let x=0;x<width-1;x++){
        const idx=[y*width+x,y*width+x+1,(y+1)*width+x+1,(y+1)*width+x],vals=idx.map(i=>values[i]);
        if(!vals.every(Number.isFinite))continue;
        const corners=[[x,y],[x+1,y],[x+1,y+1],[x,y+1]],hits=[];
        for(let a=0;a<4;a++){const b=(a+1)%4;if((vals[a]<level)===(vals[b]<level))continue;
          const t=(level-vals[a])/(vals[b]-vals[a]),px=corners[a][0]+t*(corners[b][0]-corners[a][0]),py=corners[a][1]+t*(corners[b][1]-corners[a][1]);hits.push([latAt(py),lonAt(px)]);}
        if(hits.length===2)segments.push(hits);
        // For a saddle, the cell center determines the pairing.
        if(hits.length===4){const above=vals.reduce((a,b)=>a+b)/4>=level;
          if(above===(vals[0]>=level))segments.push([hits[0],hits[1]],[hits[2],hits[3]]);
          else segments.push([hits[0],hits[3]],[hits[1],hits[2]]);}
      }
      if(segments.length)contours.push({level,segments});
    }
    return {id:message.id,bounds,width,height,field,values,u,v,support,contours,count:grid.count,radius:grid.radius};
  }
  const core={fields,allowed,filter,palette,color,build,analyze,mercator,latitude};
  if(typeof module!=="undefined"&&module.exports)module.exports=core;
  root.SurfaceCore=core;
})(typeof self!=="undefined"?self:globalThis);
