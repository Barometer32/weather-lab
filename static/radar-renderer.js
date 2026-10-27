"use strict";
// Shared by the worker and cooperative fallback. Geographic sampling, radar
// gates and reflectivity colors are identical in both paths.
globalThis.WeatherRadarRenderer = (() => {
  function inverse(latitude1, longitude1, latitude2, longitude2) {
    // Vincenty inverse on WGS84: preserve geographic alignment at 250 m gates.
    const rad=Math.PI/180,a=6378137,f=1/298.257223563,b=a*(1-f);
    const u1=Math.atan((1-f)*Math.tan(latitude1*rad)),u2=Math.atan((1-f)*Math.tan(latitude2*rad));
    const s1=Math.sin(u1),c1=Math.cos(u1),s2=Math.sin(u2),c2=Math.cos(u2);
    const difference=(longitude2-longitude1)*rad;
    let lambda=difference,sinSigma=0,cosSigma=1,sigma=0,sinAlpha=0,cosSqAlpha=1,cos2SigmaM=0;
    for(let iteration=0;iteration<10;iteration++) {
      const sin=Math.sin(lambda),cos=Math.cos(lambda),x=c2*sin,y=c1*s2-s1*c2*cos;
      sinSigma=Math.hypot(x,y);
      if(sinSigma===0)return {distance:0,bearing:0};
      cosSigma=s1*s2+c1*c2*cos;sigma=Math.atan2(sinSigma,cosSigma);
      sinAlpha=c1*c2*sin/sinSigma;cosSqAlpha=1-sinAlpha*sinAlpha;
      cos2SigmaM=cosSqAlpha>1e-14 ? cosSigma-2*s1*s2/cosSqAlpha : 0;
      const c=f/16*cosSqAlpha*(4+f*(4-3*cosSqAlpha)),old=lambda;
      lambda=difference+(1-c)*f*sinAlpha*(sigma+c*sinSigma*(cos2SigmaM+c*cosSigma*(-1+2*cos2SigmaM*cos2SigmaM)));
      if(Math.abs(lambda-old)<1e-11)break;
    }
    const uSq=cosSqAlpha*(a*a-b*b)/(b*b),A=1+uSq/16384*(4096+uSq*(-768+uSq*(320-175*uSq))),B=uSq/1024*(256+uSq*(-128+uSq*(74-47*uSq)));
    const delta=B*sinSigma*(cos2SigmaM+B/4*(cosSigma*(-1+2*cos2SigmaM*cos2SigmaM)-B/6*cos2SigmaM*(-3+4*sinSigma*sinSigma)*(-3+4*cos2SigmaM*cos2SigmaM)));
    return {distance:b*A*(sigma-delta),bearing:(Math.atan2(c2*Math.sin(lambda),c1*s2-s1*c2*Math.cos(lambda))/rad+360)%360};
  }
  function* render(request, cached) {
    const {frame, width, height, origin, zoom, colors}=request;
    const {meta,codes,rays}=frame;
    const key=JSON.stringify([width,height,origin.x,origin.y,zoom,meta.site,meta.latitude,meta.longitude,meta.firstGateMeters,meta.gates,meta.gateWidthMeters]);
    const radians=Math.PI/180,earth=6371008.8,effective=earth*4/3;
    let grid=cached?.key===key?cached:null;
    if(!grid) {
      const scale=256*Math.pow(2,zoom);
      const lat0=meta.latitude*radians,sin0=Math.sin(lat0),cos0=Math.cos(lat0);
      const longs=Array.from({length:width},(_,x)=>((origin.x+x+0.5)/scale*360-180-meta.longitude)*radians);
      const sinLon=longs.map(Math.sin),cosLon=longs.map(Math.cos);
      const distances=new Float32Array(width*height),bearings=new Uint16Array(width*height);
      for(let y=0;y<height;y++) {
        const lat=Math.atan(Math.sinh(Math.PI*(1-2*(origin.y+y+0.5)/scale)));
        const sin=Math.sin(lat),cos=Math.cos(lat);
        for(let x=0;x<width;x++) {
          const a=sinLon[x]*cos,b=cos0*sin-sin0*cos*cosLon[x],dot=sin0*sin+cos0*cos*cosLon[x];
          const i=y*width+x,ground=earth*Math.atan2(Math.hypot(a,b),dot);
          if(ground>meta.firstGateMeters+meta.gates*meta.gateWidthMeters+3000) {distances[i]=Infinity;continue;}
          const exact=inverse(meta.latitude,meta.longitude,lat/radians,meta.longitude+longs[x]/radians);
          distances[i]=exact.distance;bearings[i]=Math.floor(exact.bearing*100)%36000;
        }
        if(y%8===7)yield;
      }
      grid={key,distances,bearings};
    }
    const pixels=new Uint8ClampedArray(width*height*4);
    const tilt=(meta.nominalElevation??0.5)*radians,cosTilt=Math.cos(tilt),sinTilt=Math.sin(tilt);
    for(let y=0;y<height;y++) {
      for(let x=0;x<width;x++) {
        const i=y*width+x,distance=grid.distances[i];
        if(!Number.isFinite(distance))continue;
        const tangent=Math.tan(distance/effective),slant=effective*tangent/(cosTilt-sinTilt*tangent);
        const gate=Math.round((slant-meta.firstGateMeters)/meta.gateWidthMeters);
        if(gate<0||gate>=meta.gates)continue;
        const color=codes[rays[grid.bearings[i]]*meta.gates+gate]*4,pixel=i*4;
        pixels[pixel]=colors[color];pixels[pixel+1]=colors[color+1];pixels[pixel+2]=colors[color+2];pixels[pixel+3]=colors[color+3];
      }
      if(y%8===7)yield;
    }
    return {pixels,grid};
  }
  return {inverse,render};
})();
