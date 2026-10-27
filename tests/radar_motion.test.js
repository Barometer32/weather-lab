'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto');
const rendererSource=fs.readFileSync('static/radar-renderer.js','utf8');
const context={};vm.runInNewContext(rendererSource,context);
const renderer=context.WeatherRadarRenderer;
const meta={site:'KMPX',latitude:44.8489,longitude:-93.5655,firstGateMeters:2125,gateWidthMeters:250,gates:1700,nominalElevation:.5,azimuths:Array.from({length:360},(_,i)=>i)};
const frame={meta,codes:Uint8Array.from({length:360*meta.gates},(_,i)=>i%256),rays:Uint16Array.from({length:36000},(_,i)=>Math.floor(i/100))};
let layer,worker,timers=[],paints=0,transforms=[],removed=false;
const canvas={style:{},width:0,height:0,getContext:()=>({putImageData(){paints++;},clearRect(){}}),remove(){removed=true;}};
const map={zoom:8,on(){},off(){},getPane:()=>({appendChild(){}}),getSize:()=>({x:160,y:110}),
 getPixelOrigin:()=>({subtract:()=>({x:100,y:200})}),_getMapPanePos:()=>({x:0,y:0}),
 getZoom(){return this.zoom;},getZoomScale:(a,b)=>2**(a-b),containerPointToLatLng:()=>({lat:44.9,lng:-93.4}),
 latLngToLayerPoint:()=>({x:0,y:0}),_latLngToNewLayerPoint:()=>({x:-20,y:-10})};
const browser={window:{WeatherRadarRenderer:renderer},performance:{now:()=>Date.now()},setTimeout:fn=>{timers.push(fn);return fn;},clearTimeout:fn=>{timers=timers.filter(f=>f!==fn);},
 ImageData:class{constructor(pixels,width,height){Object.assign(this,{pixels,width,height});}},
 Worker:class{constructor(){worker=this;this.requests=[];}postMessage(r){this.requests.push(r);}terminate(){this.terminated=true;}},
 L:{Layer:{extend:methods=>{function Layer(){}Layer.prototype=methods;return Layer;}},DomUtil:{create:()=>canvas,setTransform:(...args)=>transforms.push(args)}}};
vm.runInNewContext(fs.readFileSync('static/native-radar.js','utf8'),browser);
const palette=[{dbz:10,color:'#44ff44'},{dbz:30,color:'#ffff00'},{dbz:50,color:'#ff0000'},{dbz:80,color:'#ff00ff'}],colors=browser.window.NativeRadar.colors(palette);
const request={frame,width:160,height:110,origin:{x:100,y:200},zoom:8,colors};
function complete(request,grid){const iterator=renderer.render(request,grid);let result,yields=0;do{result=iterator.next();if(!result.done)yields++;}while(!result.done);return{...result.value,yields};}
// Golden pixels were captured from the previous synchronous radar renderer.
const golden=[
 [6,'d87c28c7b982b16becdc28acf1c9ecb8ea173191318c3ee3ad081702c6cdf09a'],
 [8.5,'a0a1beede14df3fc6c281725dae932a6d3cdd10201f210c2791b188697c5c10c'],
 [11,'89b39950c125b27231598982c7661d5575802a462ff3e52551cb89e4736bd395']
];
for(const [zoom,hash]of golden){
 const scale=256*2**zoom,origin={x:(-93.462+180)/360*scale-80,y:(1-Math.asinh(Math.tan(44.925*Math.PI/180))/Math.PI)/2*scale-55};
 const req={...request,zoom,origin},first=complete(req),second=complete(req,first.grid);
 assert.equal(crypto.createHash('sha256').update(first.pixels).digest('hex'),hash,'Native gate sampling and colors stay identical');
 assert.equal(second.grid,first.grid,'Timeline changes reuse the geographic grid');assert.ok(second.yields<first.yields);
 assert.equal(complete({...req,frame:{...frame,meta:{...meta,firstGateMeters:meta.firstGateMeters+250}}},first.grid).grid===first.grid,false,'Different gate geometry invalidates the grid');
}
layer=browser.window.NativeRadar.layer();layer.onAdd(map);layer.setFrame(frame,palette);
assert.equal(worker.requests.length,1);const old=worker.requests[0];
layer._moveStart();worker.onmessage({data:{...old,pixels:new Uint8ClampedArray(old.width*old.height*4)}});assert.equal(paints,0,'Stale work cannot overwrite a moving map');
layer._reset();for(const fn of timers.splice(0))fn();assert.equal(worker.requests.length,2);
const current=worker.requests[1];worker.onmessage({data:{...current,pixels:new Uint8ClampedArray(current.width*current.height*4)}});assert.equal(paints,1);
layer._animateZoom({zoom:8.5,center:{}});assert.equal(transforms.at(-1)[2],2**.5,'The existing image scales during zoom instead of disappearing');
layer.setFrame(frame,palette);layer.setFrame(frame,palette);layer.setFrame(frame,palette);
assert.equal(worker.requests.length,3,'Only one worker request runs at a time');
worker.onmessage({data:{...worker.requests[2],pixels:new Uint8ClampedArray(160*110*4)}});assert.equal(paints,1);assert.equal(worker.requests.length,4,'Only the newest queued frame is dispatched');
worker.onmessage({data:{...worker.requests[3],pixels:new Uint8ClampedArray(160*110*4)}});assert.equal(paints,2);
layer.onRemove(map);assert.ok(worker.terminated&&removed);assert.equal(layer._canvas,null);
// The real worker uses the same generator and transfers just its finished bitmap.
let message;const workerContext={importScripts:()=>{},WeatherRadarRenderer:renderer,self:{postMessage:(result,transfer)=>{message=result;assert.equal(transfer[0],result.pixels.buffer);}}};
vm.runInNewContext(fs.readFileSync('static/radar-worker.js','utf8'),workerContext);workerContext.self.onmessage({data:{...request,id:42,topLeft:{lat:44,lng:-93}}});assert.equal(message.id,42);assert.equal(message.pixels.length,160*110*4);
// Browser worker restrictions fall back to small cooperative slices.
browser.Worker=class{constructor(){throw Error('Blocked');}};layer=browser.window.NativeRadar.layer();layer.onAdd(map);layer.setFrame(frame,palette);
let ticks=0;while(timers.length&&ticks++<1000){const next=timers.shift();next();}assert.ok(ticks>1);assert.equal(paints,3);layer.onRemove(map);
console.log('Radar motion passed: identical pixels, cached grids, animated image, latest-only worker queue, cleanup and cooperative fallback.');
