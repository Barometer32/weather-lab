'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const NOW=Date.parse('2026-11-03T04:30:00Z');
class Clock extends Date{constructor(value){super(value??NOW);}static now(){return NOW;}}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,{events:{},children:[],hidden:false,textContent:'',addEventListener(e,f){this.events[e]=f;},append(...n){this.children.push(...n);},replaceChildren(){this.children=[];}});return nodes.get(id);};
const storage=new Map(),requests=[],polls=[],events={};let subscriber,p={latitude:44.782,longitude:-93.484,label:'Shakopee, MN'};
const context={window:{WeatherLocation:{get:()=>({...p}),subscribe(fn){subscriber=fn;}}},document:{hidden:false,getElementById:get,createElement:()=>({append(){}}),addEventListener(e,f){events[e]=f;}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},Intl,Date:Clock,Number,JSON,Array,Error,AbortSignal:{timeout:()=>undefined},setInterval(fn,ms){polls.push({fn,ms});},fetch:(url,opts)=>new Promise(resolve=>requests.push({url,opts,resolve}))};
const data=(lat=44.782,lon=-93.484)=>({latitude:lat,longitude:lon,location:'Shakopee MN',updatedAt:'2026-11-03T04:00:00Z',periods:[{name:'Tonight',endTime:'2026-11-03T12:00:00Z',temperature:50,temperatureUnit:'F',isDaytime:false,detailedForecast:'Clear, with a low around 50.'}]});
const respond=(i,d,ok=true)=>requests[i].resolve({ok,json:async()=>d}),flush=()=>new Promise(setImmediate);
vm.runInNewContext(fs.readFileSync('static/forecast-views.js','utf8'),context);
(async()=>{
 assert.equal(requests.length,1,'Forecast starts loading ahead of a tab click');
 assert.equal(requests[0].url,'/api/forecast');assert.equal(requests[0].opts.method,'POST');
 assert.equal(JSON.parse(requests[0].opts.body).longitude,-93.484);
 respond(0,data());await flush();assert.equal(get('forecast-location').textContent,'Shakopee, MN');assert.equal(get('forecast-periods').children.length,1);assert.match(get('forecast-source').href,/lat=44.7820&lon=-93.4840/);
 // A new point immediately clears old content; a late old request cannot reappear.
 context.window.WeatherForecast.select('forecast');assert.equal(requests.length,2);
 p={latitude:44.98,longitude:-93.26,label:'Minneapolis, MN'};subscriber();assert.equal(get('forecast-periods').children.length,0);assert.equal(storage.size,0);
 respond(1,data());await flush();assert.equal(requests.length,3);assert.equal(get('forecast-periods').children.length,0);
 assert.equal(JSON.parse(requests[2].opts.body).latitude,44.98);
 respond(2,data(44.98,-93.26));await flush();assert.equal(get('forecast-location').textContent,'Minneapolis, MN');assert.equal(get('forecast-periods').children.length,1);
 // Even a successful HTTP response for the wrong point must be rejected.
 get('refresh-forecast').events.click();assert.equal(JSON.parse(requests[3].opts.body).force,true);
 respond(3,data());await flush();assert.match(get('forecast-status').textContent,/location could not be verified/);assert.equal(get('forecast-periods').children.length,1);
 p={latitude:44.782049,longitude:-93.484049,label:'Shakopee, MN'};subscriber();
 assert.equal(JSON.parse(requests[4].opts.body).latitude,44.782,'The request and saved-point identity use the same rounding');
 respond(4,data());await flush();assert.equal(get('forecast-status').hidden,true);
 assert.equal(polls.filter(p=>p.ms===1800000).length,1,'Regular forecast checks are every 30 minutes');
 assert.doesNotMatch(fs.readFileSync('static/forecast-views.js','utf8'),/getCurrentPosition|watchPosition/);
 console.log('Selected Forecast passed: preload, POST point, same-location source link, races, wrong-point protection, saved-copy warning and 30-minute checks.');
})().catch(e=>{console.error(e);process.exitCode=1;});
