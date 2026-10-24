'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function element(){return{value:'',children:[],events:{},hidden:false,disabled:false,textContent:'',style:{setProperty(){}},setAttribute(k,v){this[k]=v;},append(...v){this.children.push(...v);},replaceChildren(){this.children=[];},addEventListener(k,f){this.events[k]=f;},scrollIntoView(){}};}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
get('clouds').hidden=true;
let shown=[],options,fullscreen,reads=0,fail=false,zoomed=false;const events={},polls=[];
const station=(id,cover,height,lat)=>({station:id,lat,lon:0,time:'2026-10-23T11:53:00Z',layers:cover?[{cover,baseFtAGL:height}]:[]});
const stations=[station('KAAA','BKN',2700,1),station('KNEAR','OVC',12000,1.6),station('KFCM','BKN',300,7),station('KMIC','OVC',25000,7.01),station('KMSP','BKN',2700,7.02),station('KCLR','CLR',null,4),station('KSCT','SCT',5000,5),station('KVV','VV',500,6),station('KUNK','BKN',null,10),station('KDEH','BKN',500,13),station('KOUT','OVC',25000,10000),station('KOLD','BKN',1000,10),station('KOTHER','OVC',12000,10.45)];
stations.push(station('KDENSEA','OVC',12000,4),station('KDENSEB','OVC',25000,4.475));
stations.push(station('KDENSEC','OVC',25000,5),{...station('KDENSED','OVC',25000,5),lon:.375});
let data={history:Array.from({length:12},(_,i)=>({hour:new Date(Date.UTC(2026,9,23,1+i)).toISOString(),stations:stations.map(s=>['KAAA','KOLD'].includes(s.station)&&i===0?{...s,layers:[{cover:'BKN',baseFtAGL:25000}]}:s)}))};
const map={setView(){return this;},getSize(){return{x:1000,y:700};},on(name,callback){events[name]=callback;return this;},latLngToContainerPoint([lat,lon]){return{x:zoomed?(lat-7)*12000+280:lat*40,y:200+lon*40};},invalidateSize(){}};
const context={window:{WeatherFullscreen:{attach(config){fullscreen=config;}}},document:{getElementById:get,createElement:element,hidden:false},Intl,Date,Math,Number,
 fetch:async url=>{reads++;assert.equal(url,'/api/station-plots');if(fail)throw Error('Unavailable');return{ok:true,json:async()=>data};},setTimeout(){},setInterval(callback){polls.push(callback);},
 L:{map:(_id,config)=>{options=config;return map;},tileLayer:()=>({addTo(){}}),divIcon:x=>x,layerGroup:()=>({addTo(){return this;},clearLayers(){shown=[];}}),marker:(position,config)=>({bindPopup(popup){this.popup=popup;return this;},addTo(){shown.push({position,...config,popup:this.popup});return this;}})}};
vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);
vm.runInNewContext(fs.readFileSync('static/cloud-height-views.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const find=id=>shown.find(s=>s.title.startsWith(id+' ·'));
const ids=()=>shown.map(s=>s.title.split(' · ')[0]).sort();
const number=id=>find(id)?.icon.html.match(/>(\d+)<\/span>/)?.[1];
(async()=>{
 assert.equal(reads,0,'Clouds is lazy and never downloads separate upstream observations');
 get('clouds').hidden=false;context.window.WeatherCloudHeights.select('clouds');await flush();
 assert.equal(fullscreen.surfaceId,'clouds-surface');assert.equal(fullscreen.buttonId,'clouds-fullscreen');
 assert.equal(options.zoomSnap,.25);assert.equal(options.zoomDelta,.25);assert.equal(options.wheelPxPerZoomLevel,90);
 assert.equal(get('clouds-timeline').max,'11');assert.equal(get('clouds-timeline').value,'11');
 assert.equal(number('KAAA'),'3');assert.equal(number('KFCM'),'1');assert.equal(number('KDEH'),'1','formerly excluded site is eligible');
 for(const id of ['KDENSEA','KDENSEB','KDENSEC','KDENSED'])assert.ok(find(id),'small labels can fit tighter horizontal/vertical spacing: '+id);
 const cloudBoxes=shown.map(marker=>{const id=marker.title.split(' · ')[0],p=map.latLngToContainerPoint(marker.position);const rows=data.history.flatMap(h=>h.stations.filter(s=>s.station===id));const half=Math.max(...rows.map(s=>context.window.WeatherStationModel.cloudFootprint(s).right));return {left:p.x-half,right:p.x+half,top:p.y-7,bottom:p.y+7};});
 for(let i=0;i<cloudBoxes.length;i++)for(let j=0;j<i;j++){const a=cloudBoxes[i],b=cloudBoxes[j];assert.ok(a.right+.75<=b.left||b.right+.75<=a.left||a.bottom+.75<=b.top||b.bottom+.75<=a.top,'cloud labels never overlap');}
 assert.ok(find('KNEAR'),'24-pixel spacing fits small height numbers more densely than a full METAR plot');
 for(const id of ['KCLR','KSCT','KVV','KUNK','KOUT','KMIC','KMSP'])assert.equal(find(id),undefined);
 assert.match(get('clouds-status').textContent,/3 nearby heights hidden for spacing/);
 assert.equal(find('KAAA').position[0],1,'height remains at the airport, without jitter');
 assert.ok(shown.every(s=>!s.icon.html.includes('plot-temp')&&!s.icon.html.includes('<svg')),'cloud map has height numbers only');
 assert.equal(find('KOTHER'),undefined,'a wider earlier height reserves space even when the current height is one digit');
 const first=ids();get('clouds-timeline').events.input({target:{value:'0'}});
 assert.equal(number('KAAA'),'25');assert.deepEqual(ids(),first,'larger historical numbers never switch neighboring visibility');
 get('clouds-timeline').events.input({target:{value:'11'}});
 zoomed=true;events.moveend();assert.equal(number('KMIC'),'25');assert.equal(number('KMSP'),'3','closer zoom reveals neighboring heights');zoomed=false;events.moveend();
 get('clouds-station-list').open=true;get('clouds-station-list').events.toggle();
 assert.equal(get('clouds-rows').children.length,stations.length,'list includes every airport, even clear, unknown or hidden sites');
 get('clouds-search').value='KMIC';get('clouds-search').events.input();assert.equal(get('clouds-rows').children.length,1);get('clouds-search').value='';
 const complete=data;data={...data,history:data.history.map((h,i)=>({...h,stations:i===11?[]:h.stations}))};
 get('refresh-clouds').events.click();await flush();assert.equal(get('clouds-timeline').value,'10');assert.ok(shown.length);assert.match(get('clouds-status').textContent,/Waiting for the newest hour/);
 data=complete;polls[0]();await flush();assert.equal(get('clouds-timeline').value,'11','pending hour appears automatically');
 get('clouds-timeline').events.input({target:{value:'3'}});const selected=get('clouds-time').textContent;fullscreen.onResize();assert.equal(get('clouds-time').textContent,selected);
 data={...data,history:data.history.slice(1).concat({...data.history[11],hour:'2026-10-23T13:00:00Z'})};
 polls[0]();await flush();assert.equal(get('clouds-timeline').value,'2','refresh preserves selected historical hour');assert.equal(get('clouds-time').textContent.split(' · ')[0],selected.split(' · ')[0]);
 const saved=ids();fail=true;get('refresh-clouds').events.click();await flush();assert.deepEqual(ids(),saved);assert.match(get('clouds-status').textContent,/Previous reports retained/);
 get('clouds').hidden=true;const before=reads;polls[0]();await flush();assert.equal(reads,before,'hidden Clouds does not poll');
 console.log('Clouds viewer checks passed: compact spacing, matched zoom, BKN/OVC-only thousands, all-site list, stable 12-hour loop, catch-up and failed-refresh retention.');
})().catch(error=>{console.error(error);process.exitCode=1;});
