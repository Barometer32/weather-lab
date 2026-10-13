'use strict';
// Exercise the actual viewer with lightweight DOM/Leaflet adapters.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function element(){return {value:'',hidden:false,disabled:false,textContent:'',children:[],events:{},style:{setProperty(){}},classList:{toggle(){}},setAttribute(k,v){this[k]=v;},append(...v){this.children.push(...v);},replaceChildren(){this.children=[];},addEventListener(k,f){this.events[k]=f;},scrollIntoView(){}};}
const elements=new Map();
const get=id=>{if(!elements.has(id)){const n=element();n.getBoundingClientRect=()=>({top:mapTop,height:id==='metar-viewer-controls'?controlsHeight:0});elements.set(id,n);}return elements.get(id);};
get('metar-view').value='clouds';
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
const context={window:windowStub,document:{getElementById:get,createElement:element,hidden:false},Intl,Date:ClockDate,Math,Set,fetch:async()=>({ok:true,json:async()=>data}),clearTimeout(){},setTimeout(callback,delay){if(delay===0)return setTimeout(callback,0);timer={callback,delay};timers.push(timer);return timers.length;},setInterval(){throw Error("No interval polling is allowed");},L:{map:(_id,options)=>{mapOptions=options;return map;},tileLayer:()=>({addTo(){}}),layerGroup:()=>group,divIcon:x=>x,marker:(position,options)=>({bindPopup(popup){this.popup=popup;return this;},addTo(){shown.push({position,...options});return this;}})}};
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
 assert.equal(lastView.zoom,8.75);assert.equal(mapOptions.minZoom,5);
 assert.equal(mapOptions.zoomSnap,.25);assert.equal(mapOptions.zoomDelta,.25);
 assert.equal(get('metar-cloud-map').style.height,'676px');
 windowStub.innerHeight=700;windowEvents.resize();
 assert.equal(get('metar-cloud-map').style.height,'486px');
 assert.ok(mapTop+486+controlsHeight<windowStub.innerHeight);
 windowStub.innerHeight=900;windowEvents.resize();
 assert.equal(timer.delay,90000); // One scheduled prepared-data check at :00:30.
 get('metar-cloud-reset').events.click();assert.equal(lastView.zoom,8.75);
 assert.equal(find('KSCT'),undefined);assert.equal(find('KUNK'),undefined);assert.equal(find('KCLR'),undefined);
 assert.ok(shown.every(s=>!s.icon.html.includes('<circle')));
 get('metar-view').value='plots';get('metar-view').events.change();
 assert.equal(get('metar-cloud-timeline').max,'11');
 assert.equal(get('metar-cloud-timeline').value,'11');
 assert.ok(!get('metar-cloud-time').textContent.includes('Live'));
 assert.match(find('KAAA'),/rotate\(270\)/); // East wind flows west.
 assert.match(find('KAAA'),/>40<\/text>/); // 35 knots rounds to 40 mph.
 assert.match(find('KFLAG'),/>75<\/text>/);
 assert.match(find('KCLR'),/>Calm<\/text>/);assert.ok(!find('KCLR').includes('wind-arrow'));
 assert.match(find('KVAR'),/>VRB<\/text>/);assert.ok(!find('KVAR').includes('wind-arrow'));
 assert.equal(find('METRO'),undefined);
 for(const id of ['KFCM','KMIC','KMSP','KSTP'])assert.ok(find(id),id+' has its own plot');
 for(const id of ['KSGS','KCFE','KFCE'])assert.equal(find(id),undefined);
 assert.ok(shown.every(s=>s.icon.html.startsWith('<svg')&&!s.icon.html.includes('<rect')&&!s.icon.html.includes('<circle')));
 assert.ok(shown.every(s=>!s.icon.html.includes('wind-full-barb')&&!s.icon.html.includes('wind-pennant')));
 assert.ok(!get('metar-cloud-time').textContent.includes('Live'));
 assert.ok(timer.delay>0);
 const denseCount=shown.length;
 assert.equal(denseCount,11); // Independent metro sites; 80×50 px separation fits.
 zoomScale=.5;get('metar-view').events.change();
 assert.ok(shown.length<denseCount);
 assert.ok(find('KFCM'));
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
 // Direction reversal for all cardinal wind sources, including north.
 const directions=[0,90,180,270];
 const windSites=directions.map((direction,i)=>({...stations[0],station:'KW'+i,lat:i+1,wind:{speedKnots:10,direction}}));
 data={...data,history:data.history.map(h=>({...h,stations:windSites}))};
 get('metar-view').value='plots';get('refresh-metar-clouds').events.click();await flush();
 directions.forEach((direction,i)=>assert.ok(find('KW'+i).includes('rotate('+((direction+180)%360)+')')));
 // Horizontal stations can be closer than the old 90 px rule; a third plot
 // that would touch an existing arrow/label is hidden until zoom permits it.
 const project=map.latLngToContainerPoint;
 map.latLngToContainerPoint=([lat])=>({x:lat*80,y:200});
 const closeSites=[1,2,2.1].map((lat,i)=>({...stations[0],station:'KD'+i,lat}));
 data={...data,history:data.history.map(h=>({...h,stations:closeSites}))};
 get('refresh-metar-clouds').events.click();await flush();
 assert.ok(find('KD0'));assert.ok(find('KD1'));assert.equal(find('KD2'),undefined);
 map.latLngToContainerPoint=project;
 // Real airport coordinates at the new fractional desktop zoom: the three
 // focus stations fit, and nearby KSTP cannot displace KMSP.
 const geographic=[['KFCM',44.8321,-93.4705],['KMIC',45.0623,-93.3511],['KMSP',44.8852,-93.2313],['KSTP',44.9323,-93.0559]];
 const world=256*Math.pow(2,8.75);
 const mercator=([lat,lon])=>({x:world*(lon+180)/360,y:world*(.5-Math.log(Math.tan(Math.PI/4+lat*Math.PI/360))/(2*Math.PI))});
 const center=mercator([44.925,-93.35]);
 map.latLngToContainerPoint=coords=>{const p=mercator(coords);return{x:500+p.x-center.x,y:300+p.y-center.y};};
 const focusSites=geographic.map(([station,lat,lon])=>({...stations[0],station,lat,lon}));
 data={...data,history:data.history.map(h=>({...h,stations:focusSites}))};
 get('refresh-metar-clouds').events.click();await flush();
 for(const id of ['KFCM','KMIC','KMSP'])assert.ok(find(id),id+' fits at 8.75');
 assert.equal(find('KSTP'),undefined);
 map.latLngToContainerPoint=project;
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
 console.log('Station-view checks passed: ceiling height rounding, hidden non-ceilings, default/reset view, lazy list, wind flow arrows, mph conversion, individual stations and denser non-overlapping plots, scheduled refresh and selection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
