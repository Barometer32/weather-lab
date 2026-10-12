'use strict';
// Exercise the actual viewer with lightweight DOM/Leaflet adapters.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function element(){return {value:'',hidden:false,disabled:false,textContent:'',children:[],events:{},style:{setProperty(){}},classList:{toggle(){}},setAttribute(k,v){this[k]=v;},append(...v){this.children.push(...v);},replaceChildren(){this.children=[];},addEventListener(k,f){this.events[k]=f;},scrollIntoView(){}};}
const elements=new Map();
const get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
get('metar-view').value='clouds';
let shown=[],zoomScale=1,timer,mapOptions,lastView,clock=Date.UTC(2026,9,12,2,59),timers=[];
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
 ['KVAR',66,51,7,{cover:'FEW',baseFtAGL:3000}],
 ['KFLAG',67,52,65,{cover:'CLR',baseFtAGL:null}],
].map(([station,tempF,dewpointF,speedKnots,...layers],i)=>({station,tempF,dewpointF,wind:{speedKnots,direction:station==='KVAR'?null:90,variable:station==='KVAR'},layers,mapLayer:layers[0],hasCeiling:layers.some(l=>['BKN','OVC'].includes(l.cover)),time:'2026-10-12T00:53:00Z',lat:i+1,lon:0}));
const metro={station:'METRO',lat:20,lon:0,isMetro:true,available:true,tempF:75.8,dewpointF:53.6,wind:{speedKnots:12,direction:350},time:'2026-10-12T00:53:00Z'};
let data={history:Array.from({length:12},(_,i)=>({hour:new Date(Date.UTC(2026,9,11,14+i)).toISOString(),stations,metro})),live:{isLive:true,stations:stations.map(s=>({...s,tempF:99})),metro:{...metro,tempF:99}},checkedAt:'2026-10-12T02:00:00Z'};
const map={setView(center,zoom){lastView={center,zoom};return this;},on(){return this;},getZoom(){return 7;},getSize(){return{x:5000,y:5000};},latLngToContainerPoint([lat]){return{x:lat*95*zoomScale,y:lat*70*zoomScale};},invalidateSize(){}};
const group={addTo(){return this;},clearLayers(){shown=[];}};
const context={window:{},document:{getElementById:get,createElement:element,hidden:false},Intl,Date:ClockDate,Math,Set,fetch:async()=>({ok:true,json:async()=>data}),clearTimeout(){},setTimeout(callback,delay){if(delay===0)return setTimeout(callback,0);timer={callback,delay};timers.push(timer);return timers.length;},setInterval(){throw Error("No interval polling is allowed");},L:{map:(_id,options)=>{mapOptions=options;return map;},tileLayer:()=>({addTo(){}}),layerGroup:()=>group,divIcon:x=>x,marker:(position,options)=>({bindPopup(popup){this.popup=popup;return this;},addTo(){shown.push({position,...options});return this;}})}};
vm.runInNewContext(fs.readFileSync('static/cloud-views.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const find=id=>shown.find(s=>s.title.startsWith(id+' ·'))?.icon.html;
(async()=>{
 context.window.WeatherCloudViews.select('metar-clouds');await flush();
 assert.equal(get('metar-cloud-timeline').max,'11');
 assert.equal(get('metar-cloud-timeline').value,'11');
 assert.equal(shown.length,2);
 assert.match(find('KAAA'),/>6<\/span>/); // SCT is ignored; lowest BKN beats higher OVC.
 assert.match(find('KLOW'),/>1<\/span>/);
 assert.equal(lastView.zoom,7);assert.equal(mapOptions.minZoom,5);
 assert.equal(timer.delay,90000); // One scheduled prepared-data check at :00:30.
 get('metar-cloud-reset').events.click();assert.equal(lastView.zoom,7);
 assert.equal(find('KSCT'),undefined);assert.equal(find('KUNK'),undefined);assert.equal(find('KCLR'),undefined);
 assert.ok(shown.every(s=>!s.icon.html.includes('<circle')));
 get('metar-view').value='plots';get('metar-view').events.change();
 assert.equal(get('metar-cloud-timeline').max,'11');
 assert.equal(get('metar-cloud-timeline').value,'11');
 assert.ok(!get('metar-cloud-time').textContent.includes('Live'));
 assert.match(find('KAAA'),/rotate\(90\)/);
 assert.equal((find('KAAA').match(/class="wind-full-barb"/g)||[]).length,3);
 assert.equal((find('KAAA').match(/class="wind-half-barb"/g)||[]).length,1);
 assert.equal((find('KFLAG').match(/class="wind-pennant"/g)||[]).length,1);
 assert.equal((find('KFLAG').match(/class="wind-full-barb"/g)||[]).length,1);
 assert.equal((find('KFLAG').match(/class="wind-half-barb"/g)||[]).length,1);
 assert.match(find('KCLR'),/calm-ring/);assert.ok(!find('KCLR').includes('wind-staff'));
 assert.match(find('KVAR'),/VRB/);assert.ok(!find('KVAR').includes('wind-staff'));
 assert.match(find('METRO'),/>76<\/text>/);assert.ok(!find('METRO').includes('99'));
 assert.equal(find('KFCM'),undefined);assert.equal(find('KMSP'),undefined);assert.equal(find('KMIC'),undefined);
 assert.ok(shown.every(s=>s.icon.html.startsWith('<svg')&&!s.icon.html.includes('<rect')));
 assert.ok(shown.every(s=>s.icon.html.includes('<circle r="7" fill="white"')&&!s.icon.html.includes('<g fill="currentColor">')));
 assert.ok(!get('metar-cloud-time').textContent.includes('Live'));
 assert.ok(timer.delay>0);
 const denseCount=shown.length;
 assert.equal(denseCount,8); // Sites 95×70 px apart now fit instead of being skipped.
 zoomScale=.5;get('metar-view').events.change();
 assert.ok(shown.length<denseCount); // Zooming out still thins the map.
 assert.ok(find('METRO'));
 zoomScale=1;get('metar-view').events.change();assert.equal(shown.length,denseCount);
 get('metar-cloud-timeline').events.input({target:{value:'3'}});
 const hour=get('metar-cloud-time').textContent;
 get('metar-view').value='clouds';get('metar-view').events.change();
 assert.equal(get('metar-cloud-timeline').value,'3');
 assert.equal(get('metar-cloud-timeline').max,'11');
 data={...data,history:data.history.slice(1).concat({...data.history[11],hour:'2026-10-12T02:00:00Z'})};
 get('refresh-metar-clouds').events.click();await flush();
 assert.equal(get('metar-cloud-time').textContent.split(' · ')[0],hour.split(' · ')[0]);
 assert.equal(get('metar-cloud-timeline').value,'2');
 get('metar-cloud-timeline').events.input({target:{value:'11'}});
 data={...data,history:data.history.slice(1).concat({...data.history[11],hour:'2026-10-12T03:00:00Z'})};
 get('refresh-metar-clouds').events.click();await flush();
 assert.equal(get('metar-cloud-timeline').value,'11');
 assert.ok(get('metar-cloud-time').textContent.includes('10:00 PM'));
 // Cloud-height numbers use the lowest BKN/OVC, nearest thousand, min 1.
 const cases=[[0,'1'],[300,'1'],[999,'1'],[1000,'1'],[1500,'2'],[2200,'2'],[9000,'9'],[25000,'25']];
 const boundarySites=cases.map(([height],i)=>({...stations[0],station:'KB'+i,lat:i+1,layers:[{cover:'BKN',baseFtAGL:height}]}));
 data={...data,history:data.history.map(h=>({...h,stations:boundarySites}))};
 get('metar-view').value='clouds';get('refresh-metar-clouds').events.click();await flush();
 cases.forEach(([,number],i)=>assert.ok(find('KB'+i).includes('>'+number+'</span>')));
 assert.equal(get('metar-cloud-rows').children.length,0);
 get('metar-station-list').open=true;get('metar-station-list').events.toggle();
 assert.equal(get('metar-cloud-rows').children.length,cases.length);
 clock=Date.UTC(2026,9,12,3,0,30);
 const scheduled=timers.find(t=>t.delay===90000);scheduled.callback();await flush();
 assert.equal(timer.delay,60000);
 data={...data,checkedAt:'2026-10-12T03:00:00Z'};
 const count=timers.length;timer.callback();await flush();
 assert.equal(timers.length,count);
 console.log('Station-view checks passed: ceiling height rounding, hidden non-ceilings, default/reset view, lazy list, wind barbs, hourly metro, open station circles, scheduled refresh and selection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
