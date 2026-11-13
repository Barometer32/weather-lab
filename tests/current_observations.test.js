'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let now=Date.now();class Clock extends Date{static now(){return now;}}
const iso=offset=>new Date(now-offset).toISOString(),nodes=new Map(),subscriptions=new Map(),reads=[],intervals=[];
function element(){return{hidden:false,disabled:false,events:{},children:[],textContent:'',addEventListener(k,f){this.events[k]=f;},append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;}};}
const get=id=>{assert.ok(!['observations-temperature-c','observations-dewpoint-c'].includes(id),'retired Celsius secondary readout accessed');if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
const stations=['HPN20','HPN24','HPN25'].map((station,i)=>({station,displayName:['Hopkins','Edina','Minnetonka'][i],time:iso(600000-i*60000),tempF:35.4+i*.1,dewpointF:22.8,windSpeedMph:5+i,windDirection:[315,90,360][i]}));
let data={version:'hennepin-west-average-v1',stationPolicy:'approved-hennepin-west-19-v1',temperatureBasis:'reported-Fahrenheit',expectedStationCount:19,maxAgeSeconds:1800,checkedAt:iso(0),serverTime:iso(0),current:{temperatureF:35.5,dewpointF:22.8,windSpeedMph:6.6,windCardinal:'NW',observedAt:iso(480000),oldestObservedAt:iso(600000),stationCount:3,sampleCounts:{temperature:3,dewpoint:3,windSpeed:3,windDirection:3},stations},stations},fail=false;
const context={window:{WeatherPrepared:{subscribe(u,f){subscriptions.set(u,f);},async read(u,opts){reads.push([u,opts]);if(fail)throw Error('Offline');return data;}},WeatherSun:{sync(){} }},document:{getElementById:get,createElement:element,hidden:false},Intl,Date:Clock,Number,Math,setInterval(f,ms){intervals.push([f,ms]);}};
vm.runInNewContext(fs.readFileSync('static/current-observations.js','utf8'),context);
const flush=()=>new Promise(setImmediate),publish=value=>{data=value;subscriptions.get('/api/observations/current')(value);};
(async()=>{
 get('observations').hidden=true;context.window.WeatherObservations.select('metar');await flush();assert.equal(reads.length,0);
 get('observations').hidden=false;context.window.WeatherObservations.select('observations');await flush();
 assert.equal(get('observations-temperature').textContent,'36°F');assert.equal(get('observations-dewpoint').textContent,'23°F');assert.equal(get('observations-wind').textContent,'NW 7 mph');
 assert.match(get('observations-time').textContent,/ – .*3\/19 stations · oldest 10m · Partial coverage/);
 assert.match(get('observations-counts').textContent,/temperature 3\/19, dewpoint 3\/19, wind speed 3\/19/);
 assert.equal(get('observations-stations').children.length,3);
 assert.equal(get('observations-stations').children[0].children[0].textContent,'Hopkins (HPN20)');
 assert.equal(get('observations-stations').children[0].children[2].textContent,'35.4°F','station table preserves source tenths before the mean is rounded');
 assert.deepEqual(get('observations-stations').children.map(row=>row.children[4].textContent),['NW','E','N']);
 const before=get('observations-temperature').textContent;
 assert.throws(()=>subscriptions.get('/api/observations/current')({...data,version:'three-airport-rapid-main-c-v1'}),/Unexpected Mesonet/);
 assert.equal(get('observations-temperature').textContent,before,'old saved airport averages cannot enter the new Mesonet cards');
 for(let i=0;i<8;i++){
  const reports=stations.map(s=>({...s,windDirection:i*45}));
  publish({...data,checkedAt:iso(-100-i),stations:reports});
  assert.ok(get('observations-stations').children.every(row=>row.children[4].textContent===['N','NE','E','SE','S','SW','W','NW'][i]));
 }
 const exceptions=[{...stations[0],windSpeedMph:0},{...stations[1],windVariable:true},{...stations[2],windSpeedMph:null,tempF:null}];
 publish({...data,checkedAt:iso(-200),stations:exceptions});
 assert.deepEqual(get('observations-stations').children.map(row=>row.children[4].textContent),['Calm','Variable','—']);
 assert.equal(get('observations-stations').children[2].children[2].textContent,'—');
 fail=true;get('refresh-observations').events.click();await flush();assert.match(get('observations-time').textContent,/Refresh failed/);assert.equal(get('observations-temperature').textContent,before);assert.equal(reads.at(-1)[1].force,true);
 fail=false;publish({...data,checkedAt:iso(-500),current:{...data.current,temperatureF:-0.4}});assert.equal(get('observations-temperature').textContent,'0°F');
 const newer=get('observations-time').textContent;subscriptions.get('/api/observations/current')({...data,checkedAt:iso(100000),current:null});assert.equal(get('observations-time').textContent,newer,'an older response cannot erase the average');
 now+=1800001;intervals[0][0]();await flush();assert.equal(get('observations-temperature').textContent,'—','expired averages cannot look current');
 assert.equal(intervals[0][1],15000);
 publish({...data,checkedAt:iso(-2000),current:null,stations:[]});assert.match(get('observations-time').textContent,/Waiting for recent approved Hennepin West/);
 console.log('Mesonet OBSERVATIONS passed: source identity, Fahrenheit rounding, sample counts, eight-point station directions, actual time range, expiry and prepared-only refresh.');
})().catch(e=>{console.error(e);process.exitCode=1;});
