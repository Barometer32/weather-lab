'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const NOW=Date.parse('2026-11-03T04:45:00Z');let now=NOW;
class Clock extends Date{constructor(value){super(value??now);}static now(){return now;}}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',hidden:false,children:[],events:{},style:{setProperty(){}},addEventListener(e,f){this.events[e]=f;},append(...n){this.children.push(...n);},replaceChildren(){this.children=[];}});return nodes.get(id);};
const storage=new Map(),requests=[],polls=[];let sub,point={latitude:44.782,longitude:-93.484};
const context={window:{WeatherLocation:{get:()=>({...point}),subscribe(fn){sub=fn;}}},document:{hidden:false,getElementById:get,createElement:()=>({append(){}}),addEventListener(){}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},Date:Clock,Intl,Number,JSON,Error,AbortSignal:{timeout:()=>undefined},setInterval(fn,ms){polls.push({fn,ms});},fetch:(url,opts)=>new Promise(resolve=>requests.push({url,opts,resolve}))};
const value=(lat=44.782,lon=-93.484)=>({latitude:lat,longitude:lon,checkedAt:'2026-11-03T04:40:00Z',aqi:{value:80,category:'Moderate',color:'#ffff00',time:'2026-11-03T04:00:00Z',area:'Southern Twin Cities Metro',state:'MN',pollutants:[{pollutant:'PM2.5',aqi:80},{pollutant:'Ozone',aqi:72}]},mix:{display:'4',category:'Moderate',end:'2026-11-03T04:00:00Z',contributionsPct:{}},components:[],readings:[]});
const flush=()=>new Promise(setImmediate),respond=(i,d)=>requests[i].resolve({ok:true,json:async()=>d});
vm.runInNewContext(fs.readFileSync('static/local-air-views.js','utf8'),context);
(async()=>{
 assert.equal(requests[0].url,'/api/local-air-quality');assert.equal(requests[0].opts.method,'POST');respond(0,value());await flush();
 assert.equal(get('local-aqi-value').textContent,'80');assert.equal(get('local-mix-value').textContent,'4');assert.match(get('local-air-pollutants').textContent,/Ozone AQI 72/);
 assert.match(get('local-mix-category').textContent,/1–10\+/,'The separate index scale is explicit');
 get('refresh-local-air').events.click();point={latitude:44.98,longitude:-93.26};sub();
 assert.equal(get('local-aqi-value').textContent,'—');assert.equal(get('local-air-area').textContent,'');assert.equal(storage.size,0);
 respond(1,value());await flush();assert.equal(get('local-aqi-value').textContent,'—','A late old-city response cannot reappear');
 respond(2,value(44.98,-93.26));await flush();assert.equal(get('local-aqi-value').textContent,'80');
 now=NOW+4*3600000;polls.find(p=>p.ms===60000).fn();assert.equal(get('local-aqi-value').textContent,'—');assert.equal(get('local-mix-value').textContent,'—');assert.match(get('local-air-status').textContent,/unavailable/);
 assert.equal(polls.filter(p=>p.ms===1800000).length,1,'Only 30-minute checks, not five-minute downloads');
 console.log('Local air passed: separate scales, pollutant details, POST-only saved point, location races, expired values hidden and 30-minute checks.');
})().catch(e=>{console.error(e);process.exitCode=1;});
