'use strict';
// Exercise the actual viewer with lightweight DOM/Leaflet adapters.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function element(){return {value:'',hidden:false,disabled:false,textContent:'',children:[],events:{},style:{setProperty(){}},classList:{toggle(){}},setAttribute(k,v){this[k]=v;},append(...v){this.children.push(...v);},replaceChildren(){this.children=[];},addEventListener(k,f){this.events[k]=f;},scrollIntoView(){}};}
const elements=new Map();
const get=id=>{assert.notEqual(id,'metar-view');assert.ok(!id.startsWith('surface-'));if(!elements.has(id)){const n=element();n.getBoundingClientRect=()=>({top:mapTop,height:id==='metar-viewer-controls'?controlsHeight:0});elements.set(id,n);}return elements.get(id);};

let shown=[],zoomScale=1,timer,mapOptions,lastView,clock=Date.UTC(2026,9,12,2,59),timers=[],mapTop=150,controlsHeight=52;
class ClockDate extends Date {constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;}}
const stations=[
 ['KAAA',60,45,35,{cover:'SCT',baseFtAGL:2500},{cover:'BKN',baseFtAGL:6000},{cover:'OVC',baseFtAGL:7000}],
 ['KSCT',61,46,10,{cover:'SCT',baseFtAGL:3000}],
 ['KLOW',62,47,5,{cover:'OVC',baseFtAGL:300}],
 ['KCLR',63,48,0,{cover:'CLR',baseFtAGL:null}],
 ['KUNK',64,49,15,{cover:'BKN',baseFtAGL:null}],
 ['KFCM',65,50,10,{cover:'CLR',baseFtAGL:null}],
 ['KMSP',65,50,10,{cover:'CLR',baseFtAGL:null}],
 ['KMIC',65,50,10,{cover:'CLR',baseFtAGL:null}],
 ['KSTP',65,50,15,{cover:'CLR',baseFtAGL:null}],
 ['KSGS',65,50,15,{cover:'BKN',baseFtAGL:9000}],
 ['KCFE',65,50,15,{cover:'BKN',baseFtAGL:9000}],
 ['KFCE',65,50,15,{cover:'BKN',baseFtAGL:9000}],
 ['KVAR',66,51,7,{cover:'FEW',baseFtAGL:3000}],
 ['KFLAG',67,52,65,{cover:'CLR',baseFtAGL:null}],
].map(([station,tempF,dewpointF,speedKnots,...layers],i)=>({station,tempF,dewpointF,wind:{speedKnots,direction:station==='KVAR'?null:90,variable:station==='KVAR'},layers,mapLayer:layers[0],hasCeiling:layers.some(l=>['BKN','OVC'].includes(l.cover)),time:'2026-10-12T00:53:00Z',lat:i+1,lon:0}));
const metro={station:'METRO',lat:20,lon:0,isMetro:true,available:true,tempF:75.8,dewpointF:53.6,wind:{speedKnots:12,direction:350},time:'2026-10-12T00:53:00Z'};
let data={history:Array.from({length:12},(_,i)=>({hour:new Date(Date.UTC(2026,9,11,14+i)).toISOString(),stations,metro})),live:{isLive:true,stations:stations.map(s=>({...s,tempF:99})),metro:{...metro,tempF:99}},checkedAt:'2026-10-12T02:00:00Z'};
const map={setView(center,zoom){lastView={center,zoom};return this;},on(){return this;},getZoom(){return 7;},getSize(){return{x:5000,y:5000};},latLngToContainerPoint([lat]){return{x:lat*80*zoomScale,y:lat*50*zoomScale};},invalidateSize(){}};
const group={addTo(){return this;},clearLayers(){shown=[];}};
const windowEvents={};
const windowStub={innerWidth:1200,innerHeight:900,addEventListener(k,f){windowEvents[k]=f;},requestAnimationFrame(f){f();}};
const context={window:windowStub,document:{getElementById:get,createElement:element,hidden:false},Intl,Date:ClockDate,Math,Set,fetch:async url=>{assert.equal(url,'/api/station-plots');return {ok:true,json:async()=>data};},clearTimeout(){},setTimeout(callback,delay){if(delay===0)return setTimeout(callback,0);timer={callback,delay};timers.push(timer);return timers.length;},setInterval(){throw Error("No interval polling is allowed");},L:{map:(_id,options)=>{mapOptions=options;return map;},tileLayer:()=>({addTo(){}}),layerGroup:()=>group,divIcon:x=>x,marker:(position,options)=>({bindPopup(popup){this.popup=popup;return this;},addTo(){shown.push({position,...options});return this;}})}};
vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);
vm.runInNewContext(fs.readFileSync('static/cloud-views.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const find=id=>shown.find(s=>s.title.startsWith(id+' ·'))?.icon.html;
(async()=>{
 context.window.WeatherCloudViews.select('metar-clouds');await flush();
 assert.equal(get('metar-cloud-timeline').max,'11');
 assert.equal(get('metar-cloud-timeline').value,'11');
 assert.ok(timers.some(t=>t.delay===210000)); // Next prepared-data read at :02:30.
 assert.equal(shown.length,11);
 assert.match(find('KAAA'),/rotate\(270\)/); // East wind flows west.
 assert.match(find('KAAA'),/>40<\/text>/); // 35 kt => 40 mph.
 assert.match(find('KCLR'),/>Calm<\/text>/);
 assert.match(find('KVAR'),/>VRB<\/text>/);
 for(const id of ['KFCM','KMIC','KMSP','KSTP'])assert.ok(find(id));
 for(const id of ['KSGS','KCFE','KFCE','METRO'])assert.equal(find(id),undefined);
 assert.ok(shown.every(s=>s.icon.html.includes('class="plot-sky"')));
 assert.match(get('metar-cloud-status').textContent,/:50–:59/);
 get('metar-cloud-timeline').events.input({target:{value:'3'}});
 const selected=get('metar-cloud-time').textContent;
 data={...data,history:data.history.slice(1).concat({...data.history[11],hour:'2026-10-12T02:00:00Z'})};
 get('refresh-metar-clouds').events.click();await flush();
 assert.equal(get('metar-cloud-timeline').value,'2');
 assert.equal(get('metar-cloud-time').textContent.split(' · ')[0],selected.split(' · ')[0]);
 get('metar-cloud-timeline').events.input({target:{value:'11'}});
 data={...data,history:data.history.slice(1).concat({...data.history[11],hour:'2026-10-12T03:00:00Z'})};
 get('refresh-metar-clouds').events.click();await flush();
 assert.equal(get('metar-cloud-timeline').value,'11'); // Following latest stays latest.
 get('metar-station-list').open=true;get('metar-station-list').events.toggle();
 assert.equal(get('metar-cloud-rows').children.length,11);
 get('metar-cloud-search').value='KMSP';get('metar-cloud-search').events.input();
 assert.equal(get('metar-cloud-rows').children.length,1);
 zoomScale=.5;get('metar-cloud-timeline').events.input({target:{value:'11'}});
 assert.ok(shown.length<11); // Zoom decluttering retains true coordinates.
 assert.match(get("metar-cloud-status").textContent,/hidden for spacing/);
 assert.match(get("metar-cloud-status").textContent,/11 airports in view/);
 data={...data,stale:true};get('refresh-metar-clouds').events.click();await flush();
 assert.match(get('station-feed-status').textContent,/delayed/);
 console.log('METAR viewer checks passed: plot-only UI, twelve-hour selection, hourly scheduling, search, decluttering and stale status.');
})().catch(error=>{console.error(error);process.exitCode=1;});
