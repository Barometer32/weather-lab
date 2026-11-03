'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function viewer(){
 const nodes=new Map(),shown=new Map();let subscriber,reads=0;
 const get=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,children:[],events:{},style:{setProperty(){}},setAttribute(){},append(...v){this.children.push(...v);},addEventListener(name,fn){this.events[name]=fn;}});return nodes.get(id);};
 const map={setView(){return this;},getSize(){return{x:2000,y:1000};},latLngToContainerPoint([lat,lon]){return{x:lat*100,y:lon*100};},on(){},invalidateSize(){}};
 const context={window:{WeatherPrepared:{read:async()=>{reads++;return initial;},subscribe(_url,fn){subscriber=fn;}},WeatherFullscreen:{attach(){}},addEventListener(){}},document:{getElementById:get,createElement:()=>get(Symbol()),hidden:false},Intl,Math,Number,Date,Map,Set,setTimeout(){},setInterval(){},L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>({addTo(){return this;},removeLayer(marker){shown.delete(marker.title);}}),divIcon:x=>x,marker:(position,options)=>({position,...options,bindPopup(){return this;},addTo(){shown.set(this.title,this);return this;},setIcon(icon){this.icon=icon;return this;},setLatLng(pos){this.position=pos;return this;},setPopupContent(){return this;}})}};
 let initial;
 for(const path of ['static/metar-model.js','static/clouds-views.js'])vm.runInNewContext(fs.readFileSync(path,'utf8'),context);
 return {async load(data){initial=data;context.window.WeatherClouds.select('clouds');await new Promise(setImmediate);},adopt(data){subscriber(data);},ids(){return [...shown.keys()].map(s=>s.split(' · ')[0]).sort();},frame(i){get('clouds-timeline').events.input({target:{value:String(i)}});},get label(){return get('clouds-time').textContent;},get sliderMax(){return get('clouds-timeline').max;},get reads(){return reads;}};
}
const masks={KSTEADY:'111111111111',KOLDGAP:'101010101111',KONCE:'111111111011',KLEAD:'111111110111',KTRAIL:'111111111110',KABSENT:'000000000000',KCLOUD:'111111111111',KUNKNOWN:'111111111111'};
function history(patterns=masks){return {checkedAt:'2026-11-01T14:10:00Z',history:Array.from({length:12},(_,i)=>({hour:new Date(Date.UTC(2026,10,1,5+i)).toISOString(),stations:Object.entries(patterns).filter(([,mask])=>mask[i]==='1').map(([station])=>({station,lat:Object.keys(patterns).indexOf(station)+1,lon:2,time:new Date(Date.UTC(2026,10,1,4+i,53)).toISOString(),tempF:station==='KUNKNOWN'?null:50,dewpointF:40,wind:{speedKnots:10,direction:i*30},layers:[{cover:station==='KCLOUD'&&i%2?'CLR':'BKN',baseFtAGL:2000}]}))}))};}
(async()=>{
 const v=viewer(),data=history();await v.load(data);
 assert.equal(v.sliderMax,'3','Only four hourly frames are exposed');
 for(let i=0;i<4;i++){
  v.frame(i);
  assert.match(v.label,new RegExp((7+i)+':00 AM CST'),'10 AM includes 7, 8, 9 and 10 AM');
  assert.deepEqual(v.ids(),[...(i%2===0?['KCLOUD']:[]),'KOLDGAP','KSTEADY','KUNKNOWN'],'Any single missing report in the latest four suppresses the whole station; older gaps do not count');
 }
 assert.equal(data.history.length,12,'The prepared source cache is not mutated');
 assert.equal(v.reads,1,'Filtering uses the history already downloaded');

 for(let i=0;i<4;i++){v.frame(i);assert.ok(!v.ids().includes('KONCE'));assert.equal(v.ids().includes('KCLOUD'),i%2===0,'Changing ceiling is weather, not missing METAR data');}

 const complete=history(Object.fromEntries(Object.keys(masks).map(id=>[id,'111111111111'])));v.adopt(complete);v.frame(3);
 assert.ok(v.ids().includes('KONCE'),'Station returns once all four frames have a report');
 const outage=history({KSTEADY:'111111111111'});outage.history[8].stations=[];v.adopt(outage);
 for(let i=0;i<4;i++){v.frame(i);assert.deepEqual(v.ids(),[],'A wholly missing hour counts under the strict four-frame rule');}
 const short=history({KSTEADY:'111111111111'});short.history=short.history.slice(-3);v.adopt(short);assert.deepEqual(v.ids(),[],'Fewer than four frames cannot pass four-frame completeness');
 const neighbor=history({KAAA:'111111110111',KZZZ:'111111111111'});for(const f of neighbor.history)for(const s of f.stations)s.lat=5;
 v.adopt(neighbor);for(let i=0;i<4;i++){v.frame(i);assert.deepEqual(v.ids(),['KZZZ'],'Suppressed stations reserve no collision space');}
 assert.ok(neighbor.history[9].stations.some(s=>s.station==='KAAA'),'Original reports remain intact');
 console.log('Four-frame METAR continuity passed: one missing report suppresses a station, old gaps ignored, all four frames stable, rolling recovery, cloud state, empty hours, collision space and no extra downloads.');
})().catch(error=>{console.error(error);process.exitCode=1;});
