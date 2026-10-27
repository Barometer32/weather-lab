"use strict";
// Render native polar gates directly at the current map scale. No neighboring
// values are blended, and no coarse geographic image sits between data and view.
window.NativeRadar = (() => {
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
      this._map=map;this._generation=0;this._moving=false;this._working=false;this._pending=null;this._topLeft=null;
      this._canvas=L.DomUtil.create("canvas","leaflet-layer leaflet-zoom-animated native-radar-canvas");
      this._canvas.style.pointerEvents="none";this._canvas.style.transformOrigin="0 0";
      map.getPane("radar").appendChild(this._canvas);
      map.on("movestart",this._moveStart,this);
      map.on("moveend resize",this._reset,this);
      map.on("zoom",this._position,this);map.on("zoomanim",this._animateZoom,this);
      try {
        this._worker=new Worker("/static/radar-worker.js?v=map-motion-v1");
        this._worker.onmessage=event=>this._finished(event.data);
        this._worker.onerror=()=>{this._worker?.terminate();this._worker=null;this._working=false;this._draw();};
      } catch(_) {this._worker=null;}
      this._reset();
    },
    onRemove(map) {
      map.off("movestart",this._moveStart,this);map.off("moveend resize",this._reset,this);
      map.off("zoom",this._position,this);map.off("zoomanim",this._animateZoom,this);
      clearTimeout(this._timer);this._generation++;this._worker?.terminate();this._worker=null;
      this._canvas.remove();this._canvas=null;this._map=null;
    },
    setFrame(frame,palette) {this._frame=frame;this._colors=colors(palette);this._generation++;this._draw();},
    clear() {
      this._frame=null;this._generation++;this._pending=null;this._grid=null;
      if(this._canvas)this._canvas.getContext("2d").clearRect(0,0,this._canvas.width,this._canvas.height);
    },
    _moveStart() {
      this._moving=true;this._generation++;this._pending=null;clearTimeout(this._timer);
    },
    _position() {
      if(!this._topLeft)return;
      L.DomUtil.setTransform(this._canvas,this._map.latLngToLayerPoint(this._topLeft),this._map.getZoomScale(this._map.getZoom(),this._canvasZoom));
    },
    _animateZoom(event) {
      if(!this._topLeft)return;
      const offset=this._map._latLngToNewLayerPoint(this._topLeft,event.zoom,event.center);
      L.DomUtil.setTransform(this._canvas,offset,this._map.getZoomScale(event.zoom,this._canvasZoom));
    },
    _reset() {
      this._moving=false;this._generation++;this._pending=null;this._position();clearTimeout(this._timer);
      // Leave the existing geographically anchored image visible while zooming.
      // Wait briefly for wheel/touch movement to settle before resampling gates.
      this._timer=setTimeout(()=>this._draw(),80);
    },
    _draw() {
      if(!this._frame||!this._canvas||this._moving)return;
      clearTimeout(this._timer);
      const size=this._map.getSize(),origin=this._map.getPixelOrigin().subtract(this._map._getMapPanePos());
      this._pending={id:this._generation,frame:this._frame,colors:this._colors,
        width:Math.max(1,Math.round(size.x)),height:Math.max(1,Math.round(size.y)),
        origin:{x:origin.x,y:origin.y},zoom:this._map.getZoom(),topLeft:this._map.containerPointToLatLng([0,0])};
      this._dispatch();
    },
    _dispatch() {
      if(this._working||!this._pending)return;
      const request=this._pending;this._pending=null;this._working=true;
      if(this._worker){this._worker.postMessage(request);return;}
      // Worker-blocking browser settings still get a responsive fallback.
      const iterator=window.WeatherRadarRenderer.render(request,this._grid);
      const step=()=>{
        if(!this._canvas||request.id!==this._generation){this._working=false;this._dispatch();return;}
        const start=performance.now();let result;
        do {result=iterator.next();} while(!result.done&&performance.now()-start<8);
        if(!result.done){setTimeout(step,0);return;}
        this._grid=result.value.grid;this._finished({...request,pixels:result.value.pixels});
      };
      setTimeout(step,0);
    },
    _finished(result) {
      this._working=false;
      if(this._canvas&&result.id===this._generation&&!this._moving) {
        // Swap only complete results, and never let an older view overwrite a new one.
        this._canvas.width=result.width;this._canvas.height=result.height;
        this._topLeft=result.topLeft;this._canvasZoom=result.zoom;
        this._canvas.getContext("2d").putImageData(new ImageData(result.pixels,result.width,result.height),0,0);
        this._position();
      }
      this._dispatch();
    }
  });
  return {decode,colors,inverse:window.WeatherRadarRenderer.inverse,layer:()=>new Layer()};
})();
