'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function viewer(){
 const nodes=new Map(),shown=new Map();let subscriber,reads=0;
 const get=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,children:[],events:{},style:{setProperty(){}},setAttribute(){},append(...v){this.children.push(...v);},addEventListener(name,fn){this.events[name]=fn;}});return nodes.get(id);};
 const map={setView(){return this;},getSize(){return{x:2000,y:1000};},latLngToContainerPoint([lat,lon]){return{x:lat*100,y:lon*100};},on(){},invalidateSize(){}};
 const context={window:{WeatherPrepared:{read:async()=>{reads++;return initial;},subscribe(url,fn){if(url.includes('station-plots'))subscriber=fn;}},WeatherFullscreen:{attach(){}},addEventListener(){}},document:{getElementById:get,createElement:()=>get(Symbol()),hidden:false},Intl,Math,Number,Date,Map,Set,setTimeout(){},setInterval(){},L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>({addTo(){return this;},removeLayer(marker){shown.delete(marker.title);}}),divIcon:x=>x,marker:(position,options)=>({position,...options,bindPopup(){return this;},addTo(){shown.set(this.title,this);return this;},setIcon(icon){this.icon=icon;return this;},setLatLng(pos){this.position=pos;return this;},setPopupContent(){return this;}})}};
 get('metar-product').value='plots';
 let initial;
 for(const path of ['static/metar-model.js','static/metar-views.js'])vm.runInNewContext(fs.readFileSync(path,'utf8'),context);
 return {async load(data){initial=data;get('metar-product').events.change({target:{value:'plots'}});await new Promise(setImmediate);},adopt(data){subscriber(data);},icon(id){return shown.get(id+" · METAR").icon.html;},ids(){return [...shown.keys()].map(s=>s.split(' · ')[0]).sort();},frame(i){get('metar-timeline').events.input({target:{value:String(i)}});},mode(value){get('metar-product').events.change({target:{value}});},get label(){return get('metar-time').textContent;},get sliderMax(){return get('metar-timeline').max;},get reads(){return reads;}};
}
const masks={KSTEADY:'111111111111',KOLDGAP:'101010101111',KONCE:'111111111011',KLEAD:'111111110111',KTRAIL:'111111111110',KABSENT:'000000000000',KCLOUD:'111111111111',KUNKNOWN:'111111111111',KCFE:'111111111111'};
function history(patterns=masks){return {checkedAt:'2026-11-01T14:10:00Z',history:Array.from({length:12},(_,i)=>({hour:new Date(Date.UTC(2026,10,1,5+i)).toISOString(),stations:Object.entries(patterns).filter(([,mask])=>mask[i]==='1').map(([station])=>({station,lat:Object.keys(patterns).indexOf(station)+1,lon:2,time:new Date(Date.UTC(2026,10,1,4+i,53)).toISOString(),tempF:station==='KUNKNOWN'?null:50,dewpointF:40,wind:station==='KUNKNOWN'?{speedKnots:2,direction:null,variable:true}:{speedKnots:7,direction:i*30},layers:[{cover:station==='KCLOUD'&&i%2?'CLR':'BKN',baseFtAGL:2000}]}))}))};}
(async()=>{
 const v=viewer(),data=history();await v.load(data);
 assert.equal(v.sliderMax,'3','Only four hourly frames are exposed');
 for(let i=0;i<4;i++){
  v.frame(i);
  assert.match(v.label,new RegExp((7+i)+':00 AM CST'),'10 AM includes 7, 8, 9 and 10 AM');
  assert.deepEqual(v.ids(),['KCLOUD','KOLDGAP','KSTEADY','KUNKNOWN'],'PLOTS hides KCFE and any airport missing in the four displayed hours');
 }
 assert.match(v.icon("KSTEADY"),/data-mph="10"/,'Seven knots is about 8 mph, so PLOTS draws one full feather');
 assert.match(v.icon("KUNKNOWN"),/mesonet-dot/);
 assert.doesNotMatch(v.icon("KUNKNOWN"),/wind-barb|wind-shaft|wind-calm|>VRB</,'Light airport winds have a dot even with variable direction');
 assert.equal(data.history.length,12,'The prepared source cache is not mutated');
 assert.equal(v.reads,1,'Filtering uses the history already downloaded');
 v.mode('clouds');
 for(let i=0;i<4;i++){v.frame(i);assert.deepEqual(v.ids(),['KCLOUD','KOLDGAP','KSTEADY','KUNKNOWN'],'CLOUDS hides incomplete airports; valid clear and broken reports remain eligible');}
 const cloudGap=history();
 cloudGap.history[10].stations.find(s=>s.station==='KUNKNOWN').layers=[{cover:'BKN',baseFtAGL:null}];
 v.adopt(cloudGap);
 for(let i=0;i<4;i++){v.frame(i);assert.ok(!v.ids().includes('KUNKNOWN'),'A missing cloud ceiling hides that airport throughout the loop');}
 v.mode('plots');
 const complete=history(Object.fromEntries(Object.keys(masks).map(id=>[id,'111111111111'])));v.adopt(complete);v.frame(3);
 assert.ok(v.ids().includes('KONCE'),'Station remains available in a complete loop');
 const outage=history({KSTEADY:'111111111111'});outage.history[8].stations=[];v.adopt(outage);
 for(let i=0;i<4;i++){v.frame(i);assert.ok(v.ids().length,'A wholly missing source hour cannot erase the last usable loop');}
 const short=history({KSTEADY:'111111111111'});short.history=short.history.slice(-3);v.adopt(short);assert.ok(v.ids().length,'An incomplete response retains the already displayed loop');
 const neighbor=history({KAAA:'111111110111',KZZZ:'111111111111'});for(const f of neighbor.history)for(const s of f.stations)s.lat=5;
 v.adopt(neighbor);for(let i=0;i<4;i++){v.frame(i);assert.deepEqual(v.ids(),['KZZZ'],'An incomplete airport never blocks a steady neighbor');}
 assert.ok(neighbor.history[9].stations.some(s=>s.station==='KAAA'),'Original reports remain intact');
 const regional=Object.fromEntries(['KFCM','KMIC','KMSP',...Array.from({length:97},(_,i)=>'K'+String(i).padStart(3,'0'))].map(id=>[id,'111111111111']));
 function regionalHistory(){
  const data=history(regional);for(const frame of data.history)for(const station of frame.stations)if(station.station==='K096'){station.lat=7;station.lon=4;}
  return data;
 }
 const rolling=viewer(),pending=regionalHistory();pending.history.at(-1).stations=[];
 await rolling.load(pending);
 assert.match(rolling.label,/9:00 AM CST/,'Cold opening at the hour boundary uses the preceding populated loop');
 assert.ok(rolling.ids().includes('KFCM'));
 assert.equal(rolling.sliderMax,'3');
 const partial=regionalHistory();partial.history.at(-1).stations=partial.history.at(-1).stations.slice(0,20);rolling.adopt(partial);
 assert.match(rolling.label,/9:00 AM CST/,'A severely partial hourly batch is staged without changing the display');
 const below=regionalHistory();below.history.at(-1).stations=below.history.at(-1).stations.slice(0,89);rolling.adopt(below);
 assert.match(rolling.label,/9:00 AM CST/,'89% coverage keeps the preceding loop');
 const threshold=regionalHistory();threshold.history.at(-1).stations=threshold.history.at(-1).stations.slice(0,90);rolling.adopt(threshold);
 assert.match(rolling.label,/10:00 AM CST/,'Exactly 90% coverage advances the loop');
 const nearly=regionalHistory();nearly.history.at(-1).stations=nearly.history.at(-1).stations.filter(s=>s.station!=='K096');rolling.adopt(nearly);
 assert.match(rolling.label,/10:00 AM CST/,'Broadly complete data advances automatically');
 for(let i=0;i<4;i++){rolling.frame(i);assert.ok(rolling.ids().includes('KFCM'));assert.ok(!rolling.ids().includes('K096'),'A missing latest report hides the airport in all four hours');}
 const back=history(regional);back.history.at(-1).stations=[];rolling.adopt(back);
 assert.match(rolling.label,/10:00 AM CST/,'An incomplete later response cannot roll the accepted loop backwards');
 const noHistory=viewer();await noHistory.load({...history(regional),history:pending.history.slice(-3)});
 assert.match(noHistory.label,/Hourly history recovering/,'Cold start without a usable loop is explicit');
 assert.equal(rolling.reads,1,'Readiness uses downloaded data without new source calls');
 console.log('Four-frame METAR playback passed: stable PLOTS and CLOUDS rosters, rolling readiness, collision space and no extra downloads.');
})().catch(error=>{console.error(error);process.exitCode=1;});
