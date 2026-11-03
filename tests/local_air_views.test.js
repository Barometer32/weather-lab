'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const NOW=Date.parse('2026-11-03T04:45:00Z');let now=NOW;
class Clock extends Date{constructor(value){super(value??now);}static now(){return now;}}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',hidden:false,children:[],events:{},style:{setProperty(){}},addEventListener(e,f){this.events[e]=f;},append(...n){this.children.push(...n);},replaceChildren(){this.children=[];}});return nodes.get(id);};
const storage=new Map(),requests=[],polls=[];let sub,point={latitude:44.782,longitude:-93.484};
const context={window:{WeatherLocation:{get:()=>({...point}),subscribe(fn){sub=fn;}}},document:{hidden:false,getElementById:get,createElement:()=>({append(){}}),addEventListener(){}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},Date:Clock,Intl,Number,JSON,Object,Error,AbortSignal:{timeout:()=>undefined},setInterval(fn,ms){polls.push({fn,ms});},fetch:(url,opts)=>new Promise(resolve=>requests.push({url,opts,resolve}))};
const row=(pollutant,value,aqi)=>({pollutant,value,aqi,unit:'ppb',aqiType:'NowCast AQI',station:'Shakopee',stationId:'1',distanceKm:2.4,start:'2026-11-03T03:00:00Z',time:'2026-11-03T04:00:00Z'});
const value=(lat=44.782,lon=-93.484)=>({version:'local-pollutants-v2',latitude:lat,longitude:lon,checkedAt:'2026-11-03T04:40:00Z',readings:[{...row('PM2.5',8.1,40),unit:'µg/m³'},row('PM10',null,null),row('Ozone',30.5,42),{...row('NO2',3.1,2),aqiType:'Hourly AQI'}]});
const flush=()=>new Promise(setImmediate),respond=(i,d)=>requests[i].resolve({ok:true,json:async()=>d});
vm.runInNewContext(fs.readFileSync('static/local-air-views.js','utf8'),context);
(async()=>{
 assert.equal(requests[0].url,'/api/local-air-quality');assert.equal(requests[0].opts.method,'POST');respond(0,value());await flush();
 assert.equal(get('air-pm25-value').textContent,'8.1');assert.equal(get('air-pm10-value').textContent,'—');assert.match(get('air-ozone-aqi').textContent,/42/);assert.match(get('air-no2-aqi').textContent,/Hourly AQI 2/);
 assert.match(get('air-pm25-source').textContent,/Shakopee/);assert.match(get('air-pm25-time').textContent,/10:00 PM CST/);
 get('refresh-local-air').events.click();point={latitude:44.98,longitude:-93.26};sub();
 assert.equal(get('air-pm25-value').textContent,'—');assert.equal(get('air-pm25-source').textContent,'Nearest available monitor');assert.equal(storage.size,0);
 respond(1,value());await flush();assert.equal(get('air-pm25-value').textContent,'—','A late old-city response cannot reappear');
 respond(2,value(44.98,-93.26));await flush();assert.equal(get('air-pm25-value').textContent,'8.1');
 now=NOW+4*3600000;polls.find(p=>p.ms===60000).fn();assert.equal(get('air-pm25-value').textContent,'—');assert.equal(get('air-ozone-value').textContent,'—');assert.match(get('local-air-status').textContent,/unavailable/);
 assert.equal(polls.filter(p=>p.ms===1800000).length,1,'Pollutants check every 30 minutes');
 assert.doesNotMatch(fs.readFileSync('static/local-air-views.js','utf8'),/local-mix|contributionsPct/);
 console.log('Pollutants passed: four separate readings, source AQI, units, missing values, old-location races, expiry and 30-minute checks.');
})().catch(e=>{console.error(e);process.exitCode=1;});
