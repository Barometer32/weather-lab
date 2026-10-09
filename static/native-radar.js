"use strict";
// Render native polar gates directly at the current map scale. No neighboring
// values are blended, and no coarse geographic image sits between data and view.
window.NativeRadar = (() => {
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
  function decode(buffer) {
    if (buffer.byteLength < 4) throw new Error("Incomplete radar data");
    const length = new DataView(buffer).getUint32(0);
    if (length > 100000 || length+4 > buffer.byteLength) throw new Error("Invalid radar header");
    const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,4,length)));
    const codes = new Uint8Array(buffer,4+length);
    if (!Array.isArray(meta.azimuths) || meta.azimuths.length < 350 || meta.azimuths.length > 1440 ||
        !Number.isInteger(meta.gates) || meta.gates < 1 || meta.gates > 2000 ||
        codes.length !== meta.gates*meta.azimuths.length || meta.site !== "KMPX" ||
        !Number.isFinite(meta.latitude) || !Number.isFinite(meta.longitude) ||
        !Number.isFinite(meta.firstGateMeters) || !(meta.gateWidthMeters > 0) ||
        meta.azimuths.some((v,i)=>!Number.isFinite(v) || v<0 || v>=360 || (i && v<meta.azimuths[i-1]))) {
      throw new Error("Invalid native radar grid");
    }
    const rays = new Uint16Array(36000), angles = meta.azimuths;
    let right = 0;
    for (let bin=0; bin<rays.length; bin++) {
      const angle = bin/100;
      while (right<angles.length && angles[right]<angle) right++;
      const next = right%angles.length, prev = (right+angles.length-1)%angles.length;
      const distance = a=>Math.abs(((a-angle+540)%360)-180);
      rays[bin] = distance(angles[prev]) <= distance(angles[next]) ? prev : next;
    }
    return {meta,codes,rays};
  }
  function colors(palette) {
    const output = new Uint8ClampedArray(256*4);
    const rgb = color=>[1,3,5].map(i=>parseInt(color.slice(i,i+2),16));
    for(let code=86;code<256;code++) {
      const dbz=(code-2)*0.5-32;
      let upper=palette.findIndex(stop=>stop.dbz>dbz);
      if(upper<0)upper=palette.length-1;
      const lower=Math.max(0,upper-1), a=palette[lower], b=palette[upper];
      const amount=Math.min(1,Math.max(0,(dbz-a.dbz)/(b.dbz-a.dbz || 1)));
      const ca=rgb(a.color),cb=rgb(b.color);
      for(let c=0;c<3;c++)output[code*4+c]=Math.round(ca[c]+(cb[c]-ca[c])*amount);
      output[code*4+3]=220;
    }
    return output;
  }
  const Layer = L.Layer.extend({
    onAdd(map) {
      this._map=map;
      this._canvas=L.DomUtil.create("canvas","leaflet-layer leaflet-zoom-hide native-radar-canvas");
      this._canvas.style.pointerEvents="none";
      map.getPane("radar").appendChild(this._canvas);
      map.on("moveend resize",this._reset,this);
      this._reset();
    },
    onRemove(map) {map.off("moveend resize",this._reset,this);this._canvas.remove();},
    setFrame(frame,palette) {
      const old=this._frame?.meta;
      const sameSite=old?.site===frame.meta.site && old.latitude===frame.meta.latitude && old.longitude===frame.meta.longitude && old.gates===frame.meta.gates && old.gateWidthMeters===frame.meta.gateWidthMeters;
      this._frame=frame;
      this._colors=colors(palette);
      if(!sameSite)this._grid=null;
      this._draw();
    },
    clear() {this._frame=null;this._grid=null;if(this._canvas)this._canvas.getContext("2d").clearRect(0,0,this._canvas.width,this._canvas.height);},
    _reset() {
      const size=this._map.getSize();
      // Screen pixels cap memory on high-DPI phones; zooming always samples
      // the original radar gates again rather than enlarging a cached raster.
      this._canvas.width=Math.max(1,size.x);this._canvas.height=Math.max(1,size.y);
      L.DomUtil.setPosition(this._canvas,this._map.containerPointToLayerPoint([0,0]));
      this._grid=null;this._draw();
    },
    _draw() {
      if(!this._frame || !this._canvas)return;
      const {meta,codes,rays}=this._frame, width=this._canvas.width,height=this._canvas.height;
      const radians=Math.PI/180, earth=6371008.8, effective=earth*4/3;
      if(!this._grid) {
        const origin=this._map.getPixelOrigin().subtract(this._map._getMapPanePos());
        const scale=256*Math.pow(2,this._map.getZoom());
        const lat0=meta.latitude*radians, sin0=Math.sin(lat0),cos0=Math.cos(lat0);
        const longs=Array.from({length:width},(_,x)=>((origin.x+x+0.5)/scale*360-180-meta.longitude)*radians);
        const sinLon=longs.map(Math.sin),cosLon=longs.map(Math.cos);
        const distances=new Float32Array(width*height), bearings=new Uint16Array(width*height);
        for(let y=0;y<height;y++) {
          const lat=Math.atan(Math.sinh(Math.PI*(1-2*(origin.y+y+0.5)/scale)));
          const sin=Math.sin(lat),cos=Math.cos(lat);
          for(let x=0;x<width;x++) {
            const a=sinLon[x]*cos,b=cos0*sin-sin0*cos*cosLon[x],dot=sin0*sin+cos0*cos*cosLon[x];
            const i=y*width+x,ground=earth*Math.atan2(Math.hypot(a,b),dot);
            if(ground>meta.firstGateMeters+meta.gates*meta.gateWidthMeters+3000) {
              distances[i]=Infinity;continue;
            }
            const exact=inverse(meta.latitude,meta.longitude,lat/radians,meta.longitude+longs[x]/radians);
            distances[i]=exact.distance;
            bearings[i]=Math.floor(exact.bearing*100)%36000;
          }
        }
        this._grid={distances,bearings};
      }
      const context=this._canvas.getContext("2d"), image=context.createImageData(width,height), pixels=image.data;
      const tilt=(meta.nominalElevation ?? 0.5)*radians,cosTilt=Math.cos(tilt),sinTilt=Math.sin(tilt);
      const {distances,bearings}=this._grid;
      for(let i=0;i<distances.length;i++) {
        if(!Number.isFinite(distances[i]))continue;
        // Standard 4/3-earth beam geometry converts ground arc to slant range.
        const tangent=Math.tan(distances[i]/effective);
        const slant=effective*tangent/(cosTilt-sinTilt*tangent);
        const gate=Math.round((slant-meta.firstGateMeters)/meta.gateWidthMeters);
        if(gate<0 || gate>=meta.gates)continue;
        const code=codes[rays[bearings[i]]*meta.gates+gate],color=code*4,pixel=i*4;
        pixels[pixel]=this._colors[color];pixels[pixel+1]=this._colors[color+1];
        pixels[pixel+2]=this._colors[color+2];pixels[pixel+3]=this._colors[color+3];
      }
      context.putImageData(image,0,0);
    }
  });
  return {decode,colors,inverse,layer:()=>new Layer()};
})();
