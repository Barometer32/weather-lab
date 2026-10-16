'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let clock=100000,network=[],resolveSlow;
class ClockDate extends Date{static now(){return clock;}}
const stores=new Map();
const caches={async open(name){if(!stores.has(name))stores.set(name,new Map());const entries=stores.get(name);return{async match(key){return entries.get(key)?.clone();},async put(key,response){entries.set(key,response.clone());},async keys(){return [...entries.keys()];},async delete(key){return entries.delete(key);}};}};
function payload(url){
 if(url==='/api/maps')return{history:[{analysisUrl:'/map.json'}]};
 if(url==='/map.json')return{fields:{tempF:{imageUrl:'/temp.png'},dewpointF:{imageUrl:'/dew.png'},wind:{imageUrl:'/wind.png'}}};
 if(url.startsWith('/api/radar'))return{frames:[{url:'/scan.bin'}]};
 return{version:clock};
}
function create(){
 const ctx={window:{},Date:ClockDate,Map,Promise,Response,JSON,caches,Image:class{decode(){return Promise.resolve();}},fetch:async url=>{
  network.push(url);
  if(url==='/slow'&&clock>100000)return new Promise(resolve=>{resolveSlow=()=>resolve(Response.json(payload(url)));});
  return url.endsWith('.bin')||url.endsWith('.png')?new Response(new Uint8Array([0,1,2])):Response.json(payload(url));
 }};
 vm.runInNewContext(fs.readFileSync('static/weather-data.js','utf8'),ctx);return ctx.window.WeatherData;
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const service=create();
 await Promise.all([service.json('/same'),service.json('/same')]);
 assert.equal(network.filter(u=>u==='/same').length,1);
 await service.json('/slow');await flush();clock+=60000;
 let painted;
 const fresh=service.json('/slow',{onCached:value=>{painted=value.version;}});await flush();
 assert.equal(painted,100000); // Saved content arrives before the network completes.
 resolveSlow();assert.equal((await fresh).version,160000);await flush();
 const restarted=create(),before=network.length;
 assert.equal((await restarted.json('/slow')).version,160000);
 assert.equal(network.length,before); // A new page can use persistent data without a round trip.
 const responses=await Promise.all([service.asset('/one.bin'),service.asset('/one.bin')]);
 assert.equal(network.filter(u=>u==='/one.bin').length,1);
 assert.deepEqual([...new Uint8Array(await responses[0].arrayBuffer())],[0,1,2]);
 assert.deepEqual([...new Uint8Array(await responses[1].arrayBuffer())],[0,1,2]);
 service.prime();for(let i=0;i<8;i++)await flush();
 for(const url of ['/api/station-plots','/api/maps','/api/radar?site=KMPX','/map.json','/temp.png','/dew.png','/wind.png','/scan.bin'])assert.ok(network.includes(url),url);
 console.log('Weather-data checks passed: request deduplication, immediate saved content, persistent reload cache, reusable binary responses, and map/radar preloading.');
})().catch(error=>{console.error(error);process.exitCode=1;});
