'use strict';
// Exercise full station plots, including frame-stable spacing and saved-data reads.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function element(){return {value:'',children:[],events:{},hidden:false,disabled:false,textContent:'',style:{setProperty(){}},setAttribute(k,v){this[k]=v;},append(...v){this.children.push(...v);},replaceChildren(){this.children=[];},addEventListener(k,f){this.events[k]=f;},scrollIntoView(){}};}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
let clock=Date.UTC(2026,9,20,12,0,0),shown=[],timers=[],lastView,mapOptions,fail=false,reads=0,zoomed=false;
const mapEvents={};
class ClockDate extends Date{constructor(...a){super(...(a.length?a:[clock]));}static now(){return clock;}}
const row=(station,layers,lat=1)=>({station,lat,lon:0,time:'2026-10-20T11:53:00Z',layers,tempF:65,dewpointF:45,wind:{speedMph:12,direction:180},skyCover:{code:layers[0]?.cover||null,displayFraction:layers[0]?.cover==='CLR'?0:layers.length?.75:null},ceiling:layers.filter(l=>['BKN','OVC'].includes(l.cover)&&l.baseFtAGL!=null).sort((a,b)=>a.baseFtAGL-b.baseFtAGL)[0]});
const cloud=(cover,baseFtAGL)=>({cover,baseFtAGL});
const stations=[
 row('KAAA',[cloud('BKN',2700)],1),row('KCLR',[cloud('CLR',null)],2.8),
 row('KFCM',[cloud('BKN',300)],7),row('KMIC',[cloud('BKN',25000)],7.01),row('KMSP',[cloud('OVC',2700)],7.02),
 row('KCFE',[],13.01),row('KFCE',[],13.02),row('KSGS',[],13.03),
 row('KUNK',[],10),row('KDEH',[cloud('OVC',300)],13),row('KOUT',[cloud('OVC',5000)],10000)
];
let data={history:Array.from({length:12},(_,i)=>({hour:new Date(Date.UTC(2026,9,20,1+i)).toISOString(),stations,metro:row('METRO',[cloud('OVC',4000)])})),checkedAt:'2026-10-20T11:00:00Z'};
const map={setView(center,zoom){lastView={center,zoom};return this;},on(name,callback){mapEvents[name]=callback;return this;},getSize(){return {x:1000,y:700};},latLngToContainerPoint([lat]){return{x:zoomed?(lat-7)*12000+280:lat*40,y:200};},invalidateSize(){}};
const group={addTo(){return this;},clearLayers(){shown=[];}};
let fullscreenConfig;
const context={window:{WeatherFullscreen:{attach(config){fullscreenConfig=config;}}},document:{getElementById:get,createElement:element,hidden:false},Intl,Date:ClockDate,Math,Number,
 fetch:async url=>{reads++;assert.equal(url,'/api/station-plots');if(fail)throw Error('Data unavailable');return{ok:true,json:async()=>data};},setInterval(){},clearTimeout(t){if(t)t.cancelled=true;},setTimeout(callback,delay){const t={callback,delay};timers.push(t);return t;},
 L:{map:(_id,options)=>{mapOptions=options;return map;},tileLayer:()=>({addTo(){}}),layerGroup:()=>group,divIcon:x=>x,
 marker:(position,options)=>({bindPopup(popup){this.popup=popup;return this;},addTo(){shown.push({position,...options,popup:this.popup});return this;}})}};
vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);
vm.runInNewContext(fs.readFileSync('static/cloud-views.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const find=id=>shown.find(s=>s.title.startsWith(id+' ·'));
const number=id=>find(id)?.icon.html.match(/class="plot-ceiling"[^>]*>(\d+)<\/text>/)?.[1];
(async()=>{
 context.window.WeatherCloudViews.select('metar-clouds');await flush();
 assert.equal(fullscreenConfig.surfaceId,'metar-surface');assert.equal(fullscreenConfig.buttonId,'metar-fullscreen');
 assert.equal(get('metar-cloud-timeline').max,'11');assert.equal(get('metar-cloud-timeline').value,'11');
 assert.equal(number('KAAA'),'27');assert.equal(number('KFCM'),'03');
 assert.ok(find('KCLR'),'clear airports still have full temperature/wind plots');
 assert.ok(find('KUNK'),'missing clouds do not remove an otherwise available station');
 assert.ok(find('KCFE'),'formerly excluded airports remain eligible');
 for(const id of ['KMIC','KMSP','KFCE','KSGS','KDEH'])assert.equal(find(id),undefined,'overlapping airport waits for closer zoom: '+id);
 assert.equal(shown.length,5,'a compact set of nonoverlapping plots is drawn');
 const assertSpacing=()=>{
  const boxes=shown.map(marker=>{
   const id=marker.title.split(' · ')[0],rows=data.history.flatMap(h=>h.stations.filter(s=>s.station===id));
   const f=rows.map(context.window.WeatherStationModel.footprint),p=map.latLngToContainerPoint(marker.position);
   return {left:p.x+Math.min(...f.map(b=>b.left)),right:p.x+Math.max(...f.map(b=>b.right)),top:p.y+Math.min(...f.map(b=>b.top)),bottom:p.y+Math.max(...f.map(b=>b.bottom))};
  });
  for(let i=0;i<boxes.length;i++)for(let j=0;j<i;j++){
   const a=boxes[i],b=boxes[j];
   assert.ok(a.right+2<=b.left||b.right+2<=a.left||a.bottom+2<=b.top||b.bottom+2<=a.top,'rendered plot footprints leave a small clear gap');
  }
 };
 assertSpacing();
 assert.ok(find('KAAA')&&find('KCLR'),'airports only 72 pixels apart fit when their footprints clear');
 zoomed=true;mapEvents.moveend();
 for(const id of ['KFCM','KMIC','KMSP'])assert.ok(find(id),'zooming reveals close airport: '+id);
 assertSpacing();zoomed=false;mapEvents.moveend();
 for(const id of ['METRO','KOUT'])assert.equal(find(id),undefined);
 assert.ok(shown.every(s=>s.icon.html.startsWith('<svg')&&s.icon.html.includes('plot-temp')&&s.icon.html.includes('plot-speed')));
 assert.match(find('KAAA').icon.html,/class="plot-ceiling" x="55" y="16">27/);
 assert.match(find('KAAA').icon.html,/class="plot-speed" x="55" y="37">12/);
 assert.equal(find('KAAA').position[0],1,'plots stay centered on actual airports');
 assert.match(get('metar-cloud-status').textContent,/5 nearby plots hidden for spacing; zoom in/);
 assert.doesNotMatch(get('metar-cloud-status').textContent,/MADIS|Hennepin/);
 assert.equal(lastView.zoom,8.5);assert.equal(mapOptions.zoomSnap,.075);assert.equal(mapOptions.zoomDelta,.075);assert.equal(mapOptions.wheelPxPerZoomLevel,270);
 // Automatic following must not switch to a blank new hour or stop following
 // when the newest available frame is temporarily one position behind.
 const complete=data;
 data={...complete,history:complete.history.map((h,i)=>({...h,stations:i===11?[]:h.stations}))};
 get('refresh-metar-clouds').events.click();await flush();
 assert.equal(get('metar-cloud-timeline').value,'10');
 assert.ok(shown.length>0);assert.match(get('metar-cloud-status').textContent,/Waiting for.*showing the latest available hour/);
 data=complete;get('refresh-metar-clouds').events.click();await flush();
 assert.equal(get('metar-cloud-timeline').value,'11','advances automatically when the pending hour arrives');
 assert.ok(timers.some(t=>t.delay===30000),'saved data is checked at :00:30');
 assert.equal(get('metar-cloud-rows').children.length,0,'station list remains lazy');
 get('metar-station-list').open=true;get('metar-station-list').events.toggle();
 assert.equal(get('metar-cloud-rows').children.length,stations.length,'all reporting airports are searchable, even outside view');
 get('metar-cloud-search').value='KFCM';get('metar-cloud-search').events.input();assert.equal(get('metar-cloud-rows').children.length,1);
 get('metar-cloud-search').value='';
 // A large neighboring label in an earlier frame reserves the same spacing
 // on every frame, preventing thinning changes as numbers change.
 data={...data,history:data.history.map((h,i)=>({...h,stations:h.stations.map(s=>({...s,tempF:i===0?-100:s.tempF,wind:{...s.wind,direction:i*30}}))}))};
 get('refresh-metar-clouds').events.click();await flush();
 get('metar-cloud-timeline').events.input({target:{value:'0'}});
 const firstIds=shown.map(s=>s.title.split(' · ')[0]).sort();
 get('metar-cloud-timeline').events.input({target:{value:'11'}});
 assert.deepEqual(shown.map(s=>s.title.split(' · ')[0]).sort(),firstIds,'station spacing remains stable across history');
 assert.ok(firstIds.includes('KFCM'));assertSpacing();
 // A missing hour/site never borrows another report or synthetic metro data.
 data={...data,history:data.history.map((h,i)=>({...h,stations:i===0?[]:h.stations}))};
 get('refresh-metar-clouds').events.click();await flush();get('metar-cloud-timeline').events.input({target:{value:'0'}});assert.equal(shown.length,0);
 get('metar-cloud-timeline').events.input({target:{value:'3'}});fullscreenConfig.onResize();assert.equal(get('metar-cloud-timeline').value,'3','resizing fullscreen preserves history position');const selected=get('metar-cloud-time').textContent.split(' · ')[0];
 data={...data,history:data.history.slice(1).concat({...data.history[11],hour:'2026-10-20T13:00:00Z'})};
 get('refresh-metar-clouds').events.click();await flush();assert.equal(get('metar-cloud-timeline').value,'2');assert.equal(get('metar-cloud-time').textContent.split(' · ')[0],selected);
 get('metar-cloud-timeline').events.input({target:{value:'11'}});
 clock=Date.UTC(2026,9,20,12,0,30);timers.find(t=>t.delay===30000&&!t.cancelled).callback();await flush();
 assert.ok(timers.some(t=>t.delay===60000&&!t.cancelled),'wait for the prepared top-of-hour result');
 data={...data,checkedAt:'2026-10-20T12:00:00Z'};timers.findLast(t=>t.delay===60000&&!t.cancelled).callback();await flush();
 const before=shown.length;fail=true;get('refresh-metar-clouds').events.click();await flush();assert.equal(shown.length,before);assert.match(get('metar-cloud-status').textContent,/Previous reports retained/);
 get('metar-clouds').hidden=true;const readCount=reads;clock=Date.UTC(2026,9,20,13,0,30);timers.findLast(t=>t.delay>60000&&!t.cancelled).callback();await flush();assert.equal(reads,readCount);
 console.log('Full METAR viewer checks passed: compact original plots, clear/missing cloud stations, compact collision spacing, fine zoom, all airports retained in the list, fullscreen, 12-hour selection, hourly checks, and failed refresh.');
})().catch(error=>{console.error(error);process.exitCode=1;});
