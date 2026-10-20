'use strict';
// Exercise the actual cloud-only viewer with DOM and Leaflet adapters.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function element(){return {value:'',children:[],events:{},hidden:false,disabled:false,textContent:'',style:{setProperty(){}},setAttribute(k,v){this[k]=v;},append(...v){this.children.push(...v);},replaceChildren(){this.children=[];},addEventListener(k,f){this.events[k]=f;},scrollIntoView(){}};}
const elements=new Map(),get=id=>{assert.notEqual(id,'metar-view','Retired plot selector must not be accessed');if(!elements.has(id))elements.set(id,element());return elements.get(id);};
let clock=Date.UTC(2026,9,20,12,0,0),shown=[],timers=[],lastView,mapOptions,fail=false,reads=0;
class ClockDate extends Date{constructor(...a){super(...(a.length?a:[clock]));}static now(){return clock;}}
const row=(station,layers,lat=1)=>({station,lat,lon:0,time:'2026-10-20T11:53:00Z',layers});
const cloud=(cover,baseFtAGL)=>({cover,baseFtAGL});
const stations=[
 row('KAAA',[cloud('SCT',1000),cloud('OVC',25000),cloud('BKN',2700)]),
 row('KLAY',[cloud('SCT',2000),cloud('BKN',5000),cloud('OVC',10000)],3),
 row('KCLR',[cloud('CLR',null)]),row('KSCT',[cloud('SCT',2500)]),row('KFEW',[cloud('FEW',500)]),
 row('KUNK',[cloud('BKN',null)]),row('KMIX',[cloud('BKN',null),cloud('OVC',9000)]),
 row('KVIS',[cloud('VV',300)]),row('KNIL',[]),
 row('KFCM',[cloud('BKN',300)],2),row('KMIC',[cloud('BKN',25000)],2.01),row('KMSP',[cloud('OVC',2700)],2.02),
 row('KOUT',[cloud('OVC',5000)],10000)
];
let data={history:Array.from({length:12},(_,i)=>({hour:new Date(Date.UTC(2026,9,20,1+i)).toISOString(),stations,metro:row('METRO',[cloud('OVC',4000)])})),checkedAt:'2026-10-20T11:00:00Z'};
const map={setView(center,zoom){lastView={center,zoom};return this;},on(){return this;},getSize(){return {x:1000,y:700};},latLngToContainerPoint([lat]){return{x:lat*40,y:200};},invalidateSize(){}};
const group={addTo(){return this;},clearLayers(){shown=[];}};
const context={window:{},document:{getElementById:get,createElement:element,hidden:false},Intl,Date:ClockDate,Math,Number,
 fetch:async url=>{reads++;assert.equal(url,'/api/metar-clouds');if(fail)throw Error('Data unavailable');return{ok:true,json:async()=>data};},clearTimeout(t){if(t)t.cancelled=true;},setTimeout(callback,delay){const t={callback,delay};timers.push(t);return t;},
 L:{map:(_id,options)=>{mapOptions=options;return map;},tileLayer:()=>({addTo(){}}),layerGroup:()=>group,divIcon:x=>x,
 marker:(position,options)=>({bindPopup(popup){this.popup=popup;return this;},addTo(){shown.push({position,...options,popup:this.popup});return this;}})}};
vm.runInNewContext(fs.readFileSync('static/cloud-views.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const find=id=>shown.find(s=>s.title.startsWith(id+' ·'));
const number=id=>find(id)?.icon.html.match(/>(\d+)<\/span>/)?.[1];
(async()=>{
 context.window.WeatherCloudViews.select('metar-clouds');await flush();
 assert.equal(get('metar-cloud-timeline').max,'11');assert.equal(get('metar-cloud-timeline').value,'11');
 assert.equal(number('KAAA'),'27');assert.equal(number('KMIC'),'250');assert.equal(number('KFCM'),'3');assert.equal(number('KMSP'),'27');
 assert.equal(number('KLAY'),'50','lowest BKN at 5000 beats OVC at 10000 and ignores SCT');
 assert.equal(shown.length,5,'all close qualifying airports are drawn, no thinning');
 for(const id of ['KCLR','KSCT','KFEW','KUNK','KMIX','KVIS','KNIL','METRO','KOUT'])assert.equal(find(id),undefined,id+' has no number in view');
 assert.ok(shown.every(s=>s.icon.html.startsWith('<span')&&!/<svg|circle|wind/.test(s.icon.html)));
 assert.ok(shown.every(s=>s.icon.iconAnchor[0]===20));
 assert.equal(find('KAAA').position[0],1,'labels stay centered on actual airports');
 assert.equal(lastView.zoom,8.5);assert.equal(mapOptions.zoomSnap,.1);assert.equal(mapOptions.zoomDelta,.1);
 assert.ok(timers.some(t=>t.delay===30000),'saved data is checked at :00:30');
 assert.equal(get('metar-cloud-rows').children.length,0,'station list remains lazy');
 get('metar-station-list').open=true;get('metar-station-list').events.toggle();
 assert.equal(get('metar-cloud-rows').children.length,stations.length,'all reporting sites are searchable even without cloud numbers');
 get('metar-cloud-search').value='KFCM';get('metar-cloud-search').events.input();assert.equal(get('metar-cloud-rows').children.length,1);
 get('metar-cloud-search').value='';
 const cases=[[0,'0'],[100,'1'],[300,'3'],[999,'10'],[2700,'27'],[25000,'250'],[60000,'600']];
 data={...data,history:data.history.map(h=>({...h,stations:cases.map(([height],i)=>row('KB'+i,[cloud('BKN',height)],i+1))}))};
 get('refresh-metar-clouds').events.click();await flush();cases.forEach(([,value],i)=>assert.equal(number('KB'+i),value));
 // A missing hour/site never borrows another report or synthetic metro data.
 data={...data,history:data.history.map((h,i)=>({...h,stations:i===0?[]:h.stations}))};
 get('refresh-metar-clouds').events.click();await flush();get('metar-cloud-timeline').events.input({target:{value:'0'}});assert.equal(shown.length,0);
 get('metar-cloud-timeline').events.input({target:{value:'3'}});const selected=get('metar-cloud-time').textContent.split(' · ')[0];
 data={...data,history:data.history.slice(1).concat({...data.history[11],hour:'2026-10-20T13:00:00Z'})};
 get('refresh-metar-clouds').events.click();await flush();assert.equal(get('metar-cloud-timeline').value,'2');assert.equal(get('metar-cloud-time').textContent.split(' · ')[0],selected);
 get('metar-cloud-timeline').events.input({target:{value:'11'}});
 clock=Date.UTC(2026,9,20,12,0,30);timers.find(t=>t.delay===30000&&!t.cancelled).callback();await flush();
 assert.ok(timers.some(t=>t.delay===60000&&!t.cancelled),'wait for the prepared top-of-hour result');
 data={...data,checkedAt:'2026-10-20T12:00:00Z'};timers.findLast(t=>t.delay===60000&&!t.cancelled).callback();await flush();
 const before=shown.length;fail=true;get('refresh-metar-clouds').events.click();await flush();assert.equal(shown.length,before);assert.match(get('metar-cloud-status').textContent,/Previous reports retained/);
 get('metar-clouds').hidden=true;const readCount=reads;clock=Date.UTC(2026,9,20,13,0,30);timers.findLast(t=>t.delay>60000&&!t.cancelled).callback();await flush();assert.equal(reads,readCount);
 console.log('Cloud-only viewer checks passed: hundreds of feet, all close individual sites, no station-model glyphs, unknown/VV suppression, 12-hour selection, :00:30 checks, and failed refresh.');
})().catch(error=>{console.error(error);process.exitCode=1;});
