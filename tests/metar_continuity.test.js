'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function viewer(){
 const nodes=new Map(),shown=new Map();let subscriber,reads=0;
 const get=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,children:[],events:{},style:{setProperty(){}},setAttribute(){},append(...v){this.children.push(...v);},addEventListener(name,fn){this.events[name]=fn;}});return nodes.get(id);};
 const map={setView(){return this;},getSize(){return{x:2000,y:1000};},latLngToContainerPoint([lat,lon]){return{x:lat*100,y:lon*100};},on(){},invalidateSize(){}};
 const context={window:{WeatherPrepared:{read:async()=>{reads++;return initial;},subscribe(_url,fn){subscriber=fn;}},WeatherFullscreen:{attach(){}},addEventListener(){}},document:{getElementById:get,createElement:()=>get(Symbol()),hidden:false},Intl,Math,Number,Date,Map,Set,setTimeout(){},setInterval(){},L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>({addTo(){return this;},removeLayer(marker){shown.delete(marker.title);}}),divIcon:x=>x,marker:(position,options)=>({position,...options,bindPopup(){return this;},addTo(){shown.set(this.title,this);return this;},setIcon(icon){this.icon=icon;return this;},setLatLng(pos){this.position=pos;return this;},setPopupContent(){return this;}})}};
 let initial;
 for(const path of ['static/metar-model.js','static/metar-views.js'])vm.runInNewContext(fs.readFileSync(path,'utf8'),context);
 return {async load(data){initial=data;context.window.WeatherMetars.select('metar');await new Promise(setImmediate);},adopt(data){subscriber(data);},ids(){return [...shown.keys()].map(s=>s.split(' · ')[0]).sort();},frame(i){get('metar-timeline').events.input({target:{value:String(i)}});},mode(value){get('metar-product').events.change({target:{value}});},get reads(){return reads;}};
}
const masks={KSTEADY:'111111111111',KTWICE:'101011111111',KTHREE:'101010111111',KONCE:'110001111111',KLEAD:'000111111111',KTRAIL:'111111110000',KABSENT:'000000000000',KCLOUD:'111111111111',KUNKNOWN:'111111111111'};
function history(patterns=masks){return {checkedAt:'2026-11-01T14:10:00Z',history:Array.from({length:12},(_,i)=>({hour:new Date(Date.UTC(2026,10,1,3+i)).toISOString(),stations:Object.entries(patterns).filter(([,mask])=>mask[i]==='1').map(([station],j)=>({station,lat:Object.keys(patterns).indexOf(station)+1,lon:2,time:new Date(Date.UTC(2026,10,1,2+i,53)).toISOString(),tempF:station==='KUNKNOWN'?null:50,dewpointF:40,wind:{speedKnots:10,direction:i*30},layers:[{cover:station==='KCLOUD'&&i%2?'CLR':'BKN',baseFtAGL:2000}]}))}))};}
(async()=>{
 const v=viewer(),data=history();await v.load(data);
 for(let i=0;i<12;i++){
  v.frame(i);
  const expected=Object.entries(masks).filter(([id,mask])=>!['KTWICE','KTHREE'].includes(id)&&mask[i]==='1').map(([id])=>id).sort();
  assert.deepEqual(v.ids(),expected,'Two returns hide the entire station in every frame; single gaps stay honest: '+i);
 }
 assert.equal(v.reads,1,'All filtering uses the history already downloaded');
 v.mode('clouds');
 for(let i=0;i<12;i++){v.frame(i);assert.ok(!v.ids().includes('KTWICE'));assert.equal(v.ids().includes('KCLOUD'),i%2===0,'Changing ceiling is weather, not station instability');}
 v.mode('plots');
 const complete=history(Object.fromEntries(Object.keys(masks).map(id=>[id,'111111111111'])));v.adopt(complete);v.frame(11);
 assert.ok(v.ids().includes('KTWICE'),'Station becomes eligible again as repeated gaps leave the rolling history');
 const outage=history({KSTEADY:'111111111111'});for(const i of [2,4])outage.history[i].stations=[];v.adopt(outage);
 for(let i=0;i<12;i++){v.frame(i);assert.deepEqual(v.ids(),[2,4].includes(i)?[]:['KSTEADY'],'Entire-feed missing frames never count as individual station failures');}
 const neighbor=history({KAAA:'101011111111',KZZZ:'111111111111'});for(const f of neighbor.history)for(const s of f.stations)s.lat=5;
 v.adopt(neighbor);for(let i=0;i<12;i++){v.frame(i);assert.deepEqual(v.ids(),['KZZZ'],'Suppressed stations cannot reserve collision space and hide a steady neighbor');}
 assert.ok(neighbor.history[0].stations.some(s=>s.station==='KAAA'),'Raw reports remain intact');
 console.log('METAR continuity passed: two completed gaps, one gap, edge gaps, rolling recovery, cloud changes, feed outages, collision space and no extra downloads.');
})().catch(error=>{console.error(error);process.exitCode=1;});
