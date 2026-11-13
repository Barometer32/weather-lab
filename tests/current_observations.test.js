'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let now=Date.now();class Clock extends Date{static now(){return now;}}
const iso=offset=>new Date(now-offset).toISOString(),nodes=new Map(),subscriptions=new Map(),reads=[],intervals=[];
function element(){return{hidden:false,disabled:false,events:{},children:[],textContent:'',addEventListener(k,f){this.events[k]=f;},append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;}};}
const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
const stations=['KFCM','KMSP','KMIC'].map((station,i)=>({station,time:iso(300000),tempC:4+i,dewpointC:1,windSpeedMph:5+i,windDirection:[315,90,undefined][i],rawOb:station+' 131700Z AUTO '+['31505KT','09006KT','36007KT'][i]+' 10SM CLR 04/01 RMK MADISHF'}));
let data={version:'three-airport-rapid-main-c-v1',temperatureBasis:'main-XX/XX',checkedAt:iso(0),serverTime:iso(0),current:{temperatureF:41,temperatureC:5,dewpointF:33.8,dewpointC:1,windSpeedMph:6.6,windCardinal:"NW",observedAt:iso(300000),stations},stations},fail=false;
const context={window:{WeatherPrepared:{subscribe(u,f){subscriptions.set(u,f);},async read(u,opts){reads.push([u,opts]);if(fail)throw Error('Offline');return data;}},WeatherSun:{sync(){} }},document:{getElementById:get,createElement:element,hidden:false},Intl,Date:Clock,Number,Math,setInterval(f,ms){intervals.push([f,ms]);}};
vm.runInNewContext(fs.readFileSync('static/current-observations.js','utf8'),context);
const flush=()=>new Promise(setImmediate),publish=value=>{data=value;subscriptions.get('/api/observations/current')(value);};
(async()=>{
 get('observations').hidden=true;context.window.WeatherObservations.select('metar');await flush();assert.equal(reads.length,0);
 get('observations').hidden=false;context.window.WeatherObservations.select('observations');await flush();
 assert.equal(get('observations-temperature').textContent,'41°F');assert.equal(get('observations-temperature-c').textContent,'5.0°C');
 assert.equal(get('observations-dewpoint').textContent,'34°F');assert.equal(get('observations-wind').textContent,'NW 7 mph');
 assert.match(get('observations-time').textContent,/5m old · 3 airports/);assert.equal(get('observations-stations').children.length,3);
 assert.deepEqual(get('observations-stations').children.map(row=>row.children[4].textContent),['NW','E','N']);
 assert.equal(get('observations-stations').children[0].children[5].textContent,'5 mph');
 const directions=['N','NE','E','SE','S','SW','W','NW'];
 for(let i=0;i<8;i++){
  const reports=stations.map(s=>({...s,windDirection:i*45}));
  publish({...data,checkedAt:iso(-100-i),current:{...data.current,stations:reports}});
  assert.ok(get('observations-stations').children.every(row=>row.children[4].textContent===directions[i]));
 }
 const exceptions=[{...stations[0],windSpeedMph:0},{...stations[1],windVariable:true},{...stations[2],windSpeedMph:null}];
 publish({...data,checkedAt:iso(-200),current:{...data.current,stations:exceptions}});
 assert.deepEqual(get('observations-stations').children.map(row=>row.children[4].textContent),['Calm','Variable','—']);
 publish({...data,checkedAt:iso(-500),current:{...data.current,temperatureC:1/3,temperatureF:32.6,dewpointF:-2.6}});assert.equal(get('observations-temperature').textContent,'33°F');assert.equal(get('observations-dewpoint').textContent,'-3°F');
 publish({...data,checkedAt:iso(-550),current:{...data.current,temperatureF:-0.4}});assert.equal(get('observations-temperature').textContent,'0°F');
 publish({...data,checkedAt:iso(-600),current:{...data.current,temperatureC:5,temperatureF:41}});
 fail=true;get('refresh-observations').events.click();await flush();assert.match(get('observations-time').textContent,/Refresh failed/);assert.equal(get('observations-temperature').textContent,'41°F');assert.equal(reads.at(-1)[1].force,true);
 fail=false;publish({...data,checkedAt:iso(-1000),waiting:true});assert.match(get('observations-time').textContent,/Waiting for matching reports/);
 const newer=get('observations-time').textContent;subscriptions.get('/api/observations/current')({...data,checkedAt:iso(100000),current:null});assert.equal(get('observations-time').textContent,newer,'an older response cannot erase the average');
 now+=3600001;intervals[0][0]();await flush();assert.equal(get('observations-temperature').textContent,'—','expired averages cannot look current');
 assert.equal(intervals[0][1],15000);
 publish({...data,checkedAt:iso(-2000),current:null,stations:[]});assert.match(get('observations-time').textContent,/Waiting for complete matching/);
 console.log('OBSERVATIONS passed: separate tab, units, actual timestamp, all-three table, waiting state, expiry, refresh retention and prepared-only polling.');
})().catch(e=>{console.error(e);process.exitCode=1;});
