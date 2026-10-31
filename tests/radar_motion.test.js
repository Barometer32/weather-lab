'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto');
let paints=0,pixels,position,removed=false;const events={};
const canvas={style:{},width:0,height:0,getContext:()=>({createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),putImageData:image=>{pixels=image.data;paints++;},clearRect(){pixels=null;}}),remove(){removed=true;}};
const browser={window:{},Worker:class{constructor(){throw Error('Radar timeline must not queue worker rendering');}},
 L:{Layer:{extend:methods=>{function Layer(){}Layer.prototype=methods;return Layer;}},DomUtil:{create:()=>canvas,setPosition:(c,p)=>{position=p;}}}};
vm.runInNewContext(fs.readFileSync('static/native-radar.js','utf8'),browser);
const radar=browser.window.NativeRadar;
const meta={site:'KMPX',latitude:44.8489,longitude:-93.5655,firstGateMeters:2125,gateWidthMeters:250,gates:1700,nominalElevation:.5,azimuths:Array.from({length:360},(_,i)=>i)};
const frame={meta,codes:Uint8Array.from({length:360*meta.gates},(_,i)=>i%256),rays:Uint16Array.from({length:36000},(_,i)=>Math.floor(i/100))};
const palette=[{dbz:10,color:'#44ff44'},{dbz:30,color:'#ffff00'},{dbz:50,color:'#ff0000'},{dbz:80,color:'#ff00ff'}];
// Golden pixels captured before the worker renderer was introduced.
const golden=[
 [6,'d87c28c7b982b16becdc28acf1c9ecb8ea173191318c3ee3ad081702c6cdf09a'],
 [8.5,'a0a1beede14df3fc6c281725dae932a6d3cdd10201f210c2791b188697c5c10c'],
 [11,'89b39950c125b27231598982c7661d5575802a462ff3e52551cb89e4736bd395']
];
for(const [zoom,hash]of golden){
 const width=160,height=110,scale=256*2**zoom,origin={x:(-93.462+180)/360*scale-80,y:(1-Math.asinh(Math.tan(44.925*Math.PI/180))/Math.PI)/2*scale-55};
 const map={on:(name,fn)=>{events[name]=fn;},off:name=>{delete events[name];},getPane:()=>({appendChild(){}}),getSize:()=>({x:width,y:height}),
 getPixelOrigin:()=>({subtract:()=>origin}),_getMapPanePos:()=>({x:0,y:0}),getZoom:()=>zoom,containerPointToLayerPoint:()=>({x:17,y:23})};
 const layer=radar.layer();layer.onAdd(map);layer.setFrame(frame,palette);
 assert.equal(crypto.createHash('sha256').update(pixels).digest('hex'),hash,'Original sampling and colors preserved');
 const grid=layer._grid,count=paints;
 for(let i=0;i<4;i++){
   const codes=new Uint8Array(frame.codes.length).fill(i%2?126:186);
   layer.setFrame({...frame,codes},palette);
   assert.equal(paints,count+i+1,'Every slider frame is painted before setFrame returns');
   assert.equal(layer._grid,grid,'The timeline reuses the expensive geographic projection');
 }
 layer._reset();assert.notEqual(layer._grid,grid,'A map move refreshes geographic sampling');
 assert.equal(position.x,17);assert.equal(position.y,23);
 layer.clear();assert.equal(pixels,null);layer.onRemove(map);assert.ok(removed);assert.equal(Object.keys(events).length,0);
}
// Exercise the actual radar map initializer to check the new zoom controls.
const app=fs.readFileSync('static/app.js','utf8'),init=app.slice(app.indexOf('function initMap()'),app.indexOf('function renderRadarLegend('));
let options;const panes={};const mockMap={setView(){return this;},createPane:id=>{panes[id]={style:{}};},getPane:id=>panes[id]};
const initContext={L:{map:(id,o)=>{assert.equal(id,'map');options=o;return mockMap;},tileLayer:()=>({addTo:()=>({on(){}})})},NativeRadar:{layer:()=>({addTo:()=>({})})},window:{WeatherRadarRoads:{addTo(){}}},$(){}};
vm.runInNewContext('let map,nativeLayer;const radarSite="KMPX",radarViews={KMPX:{center:[44.925,-93.462],zoom:8}};'+init+';initMap();',initContext);
assert.equal(options.zoomSnap,.5);assert.equal(options.zoomDelta,.5);assert.equal(options.wheelPxPerZoomLevel,60);
assert.equal(options.minZoom,5);assert.equal(options.maxZoom,13);
const html=fs.readFileSync('static/index.html','utf8');
assert.ok(html.includes('native-radar.js?v=radar-timeline-v2'));assert.ok(html.includes('app.js?v=hennepin-observations-v2'));
assert.ok(html.includes('metar-views.js?v=metar-airports-v4'),'Keep the successful METAR optimization');
assert.doesNotMatch(html,/radar-renderer\.js|radar-worker\.js/);
console.log('Radar checks passed: original pixels, synchronous slider frames, cached projection, half-level zoom and preserved METAR optimization.');

let reset,restored;
vm.runInNewContext(app.slice(app.indexOf('$("radar-reset-view")'),app.indexOf('$("timeline").addEventListener')),
 {map:{setView(center,zoom){restored={center,zoom};}},window:{WeatherDefaultViews:{radar(){return{center:[45,-94],zoom:9.5};}}},$(){return{addEventListener(event,fn){assert.equal(event,'click');reset=fn;}}}});
reset();assert.equal(restored.zoom,9.5);assert.deepEqual(Array.from(restored.center),[45,-94]);
