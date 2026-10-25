'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function element(){return{value:'',events:{},children:[],hidden:false,disabled:false,textContent:'',style:{setProperty(){}},setAttribute(k,v){this[k]=v;},append(...v){this.children.push(...v);},addEventListener(k,f){this.events[k]=f;}};}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};get('metar-product').value='clouds';
const stations=[{station:'KFCM',lat:3,lon:1,time:'2026-10-24T17:53:00Z',reportType:'METAR',tempF:71,dewpointF:50,wind:{speedMph:7,direction:270},layers:[{cover:'BKN',baseFtAGL:2700}]},{station:'KNEAR',lat:3.01,lon:1,time:'2026-10-24T17:53:00Z',reportType:'METAR',tempF:70,dewpointF:49,wind:{speedMph:0},layers:[{cover:'CLR',baseFtAGL:null}]},{station:'KMSP',lat:9,lon:2,time:'2026-10-24T17:53:00Z',reportType:'METAR',tempF:72,dewpointF:51,wind:{speedMph:10,direction:225},layers:[{cover:'OVC',baseFtAGL:25000}]}];
let data={checkedAt:'2026-10-24T18:01:00Z',serverTime:'2026-10-24T18:02:00Z',history:Array.from({length:12},(_,i)=>({hour:new Date(Date.UTC(2026,9,24,7+i)).toISOString(),stations:stations.map(s=>({...s,tempF:i===0?100:s.tempF}))}))};
let reads=0,fail=false,shown=[],zoomed=false,fullConfig,subscriber;const callbacks={};
const map={setView(){return this;},getSize(){return{x:1000,y:700};},on(name,fn){callbacks[name]=fn;},latLngToContainerPoint([lat,lon]){return{x:zoomed?(lat-3)*5000+100:lat*50,y:lon*50};},invalidateSize(){}};
const context={window:{WeatherPrepared:{read:async()=>{reads++;if(fail)throw Error('Unavailable');return data;},subscribe(url,fn){assert.equal(url,'/api/station-plots');subscriber=fn;}},WeatherFullscreen:{attach(c){fullConfig=c;}},WeatherSun:{sync(){}}},document:{getElementById:get,createElement:element,hidden:false},Intl,Math,Date,Number,Map,Set,setTimeout(){},setInterval(){},L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>({addTo(){return this;},clearLayers(){shown=[];}}),divIcon:x=>x,marker:(position,config)=>({bindPopup(){return this;},addTo(){shown.push({position,...config});}})}};
vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);vm.runInNewContext(fs.readFileSync('static/metar-views.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve)),ids=()=>shown.map(s=>s.title.split(' · ')[0]);
(async()=>{
 context.window.WeatherMetars.select('metar');await flush();assert.equal(shown.length,3,'cloud view shows every airport');assert.equal(reads,1);assert.equal(get('metar-timeline').max,'11');assert.equal(fullConfig.surfaceId,'metar-surface');
 assert.match(shown[0].icon.html,/>3<\/text>/);assert.match(shown[1].icon.html,/cloud-dot[^>]*r="1.9"/);assert.match(shown[2].icon.html,/>25<\/text>/);
 assert.deepEqual(Array.from(shown[0].position),[3,1]);
 get('metar-timeline').events.input({target:{value:'2'}});const selected=get('metar-time').textContent;
 for(const mode of ['wind','dewpoint','temperature','clouds']){
  get('metar-product').value=mode;get('metar-product').events.change();assert.equal(reads,1,'dropdown never fetches another observation source');assert.equal(get('metar-time').textContent,selected,'dropdown retains selected hour');
  const html=shown[0].icon.html;
  if(mode==='clouds')assert.doesNotMatch(html,/wind-vector|plot-speed|plot-temp|plot-dew/);
  if(mode==='wind'){assert.match(html,/wind-vector/);assert.match(html,/plot-speed/);assert.doesNotMatch(html,/plot-temp|plot-dew|plot-ceiling/);assert.match(html,/rotate\(90\)/,'west wind points downwind east');}
  if(mode==='temperature'){assert.match(html,/plot-temp/);assert.doesNotMatch(html,/plot-dew|plot-speed|wind-vector|plot-ceiling/);assert.equal(shown.length,2,'only touching value labels are thinned');}
  if(mode==='dewpoint'){assert.match(html,/plot-dew/);assert.doesNotMatch(html,/plot-temp|plot-speed|wind-vector|plot-ceiling/);}
 }
 get('metar-product').value='temperature';get('metar-product').events.change();const before=ids();get('metar-timeline').events.input({target:{value:'0'}});assert.deepEqual(ids(),before,'larger historical values keep density stable');zoomed=true;callbacks.moveend();assert.ok(ids().includes('KNEAR'),'zoom reveals nearby airports');zoomed=false;
 get('metar-timeline').events.input({target:{value:'3'}});const hour=get('metar-time').textContent;
 data={...data,history:data.history.slice(1).concat({...data.history[11],hour:'2026-10-24T19:00:00Z'})};subscriber(data);assert.equal(get('metar-timeline').value,'2');assert.equal(get('metar-time').textContent,hour.replace('4/12','3/12'));
 const kept=ids();fail=true;get('refresh-metar').events.click();await flush();assert.deepEqual(ids(),kept);assert.match(get('metar-status').textContent,/Previous reports retained/);
 console.log('Four METAR products passed: isolated variables, all cloud sites, exact anchors, stable spacing, shared hour/zoom, no dropdown fetch, refresh retention.');
})().catch(e=>{console.error(e);process.exitCode=1;});
