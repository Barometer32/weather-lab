'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map(),events={},timers=[],panes=new Map(),pending=new Map();
let shown=[],fetches=[],clock=Date.UTC(2026,9,16,17,1);
class ClockDate extends Date{constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;}}
function element(){return{value:'',hidden:false,disabled:false,children:[],events:{},style:{setProperty(){}},setAttribute(k,v){this[k]=v;},replaceChildren(){this.children=[];},append(...v){this.children.push(...v);},addEventListener(k,f){this.events[k]=f;}};}
function get(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}
get('surface-field').value='tempF';get('maps').hidden=true;
const history=Array.from({length:12},(_,i)=>({hour:new Date(Date.UTC(2026,9,16,6+i)).toISOString(),stationCount:364,analysisUrl:`/maps/${i}.json`}));
let dataset={hour:history.at(-1).hour,checkedAt:'2026-10-16T17:02:00Z',history,stale:false};
const map={fitBounds(){},createPane(n){const p={style:{}};panes.set(n,p);return p;},getPane(n){return panes.get(n);},invalidateSize(){}};
const group={addTo(){return this;},clearLayers(){shown=[];}};
const layer=(kind,value)=>({on(){return this;},addTo(){shown.push({kind,value});return this;}});
const context={window:{},document:{hidden:false,getElementById:get,createElement:element,addEventListener(k,f){events[k]=f;}},Date:ClockDate,Intl,Math,Map,Set,clearTimeout(t){if(t)t.cleared=true;},setTimeout(callback,delay){if(delay===0)return setTimeout(callback,0);const t={callback,delay};timers.push(t);return t;},fetch:async url=>{fetches.push(url);if(url==='/api/maps')return{ok:true,json:async()=>dataset};return{ok:true,json:()=>new Promise(resolve=>pending.set(url,resolve))};},L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>group,imageOverlay:(url)=>layer('image',url),geoJSON:(geo)=>layer('contours',geo),divIcon:x=>x,marker:(_pos,options)=>layer('vector',options)}};
vm.runInNewContext(fs.readFileSync('static/maps.js','utf8'),context);
const viewer=context.window.WeatherMaps,flush=()=>new Promise(resolve=>setImmediate(resolve));
function manifest(hour){
 const palette=[[0,'#0f0'],[5,'#ff0'],[10,'#f00'],[15,'#f00']];
 const base={palette,paletteMode:'discrete',interval:5,contours:{type:'FeatureCollection',features:[]},arrows:[],used:300,supportedCells:20000,qc:{suspect:1,unverified:12}};
 return{hour,bounds:[[40,-100],[50,-85]],fields:{tempF:{...base,imageUrl:hour+'/temp.png'},dewpointF:{...base,imageUrl:hour+'/dew.png'},wind:{...base,imageUrl:hour+'/wind.png',arrows:[{lat:45,lon:-93,direction:359,speed:12}]}}};
}
async function resolveFrame(i){pending.get(history[i].analysisUrl)(manifest(history[i].hour));await flush();}
const scrub=i=>get('surface-timeline').events.input({target:{value:String(i)}});
const field=value=>{get('surface-field').value=value;get('surface-field').events.change();};
(async()=>{
 assert.equal(fetches.length,0);assert.ok(timers.some(t=>t.delay===90000)); // Next read at :02:30.
 viewer.select('metar-clouds');assert.equal(fetches.length,0);
 get('maps').hidden=false;viewer.select('maps');await flush();
 assert.equal(get('surface-timeline').max,'11');assert.equal(get('surface-timeline').value,'11');
 await resolveFrame(11);
 assert.equal(shown.filter(x=>x.kind==='image').length,1);assert.equal(shown.filter(x=>x.kind==='vector').length,0);
 assert.match(get('surface-legend').children[0].textContent,/5 °F bands/);
 const temperatureScale=get('surface-legend').children[1].style.background;
 assert.match(get('surface-feed-status').textContent,/364 eligible airport METARs/);
 assert.match(get('surface-status').textContent,/1 suspect values excluded/);
 // A stale response from a prior slider position cannot paint over a new selection.
 scrub(10);await flush();scrub(9);await flush();await resolveFrame(10);
 assert.equal(shown.filter(x=>x.kind==='image').length,0);
 await resolveFrame(9);assert.equal(shown.find(x=>x.kind==='image').value,history[9].hour+'/temp.png');
 field('wind');await flush();assert.equal(get('surface-timeline').value,'11');
 assert.match(shown.find(x=>x.kind==='vector').value.icon.html,/rotate\(179\)/);
 assert.equal(shown.find(x=>x.kind==='vector').value.interactive,false);
 assert.match(get('surface-legend').children[0].textContent,/5 mph bands/);
 field('dewpointF');await flush();assert.equal(get('surface-legend').children[1].style.background,temperatureScale);
 field('tempF');await flush();assert.equal(get('surface-timeline').value,'9');
 const requests=fetches.length;scrub(10);await flush();assert.equal(fetches.length,requests); // Reuse cached history.
 const next={hour:'2026-10-16T18:00:00Z',stationCount:360,analysisUrl:'/maps/next.json'};
 dataset={...dataset,hour:next.hour,history:history.slice(1).concat(next)};
 get('refresh-maps').events.click();await flush();assert.equal(get('surface-timeline').value,'9'); // Same historical hour.
 field('wind');await flush();assert.equal(get('surface-timeline').value,'11');
 pending.get(next.analysisUrl)(manifest(next.hour));await flush();
 get('surface-play').events.click();await flush();assert.equal(get('surface-play')['aria-pressed'],'true');
 await resolveFrame(1);
 viewer.select('radar');assert.equal(get('surface-play')['aria-pressed'],'false');
 // During the collection's processing grace, an old index still gets retried.
 clock=Date.UTC(2026,9,16,18,2,30);dataset={...dataset,checkedAt:'2026-10-16T17:02:00Z',stale:false};
 get('refresh-maps').events.click();await flush();assert.ok(timers.some(t=>t.delay===60000&&!t.cleared));
 assert.ok(!fs.readFileSync('static/maps.js','utf8').includes('circleMarker'));
 console.log('Maps viewer checks passed: twelve-hour fields, palettes, vectors, cache, race protection, playback, refresh preservation and hourly retry.');
})().catch(error=>{console.error(error);process.exitCode=1;});
