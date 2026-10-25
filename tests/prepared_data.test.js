'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync('static/prepared-data.js','utf8');
const cacheRows=new Map();const cache={async put(url,response){cacheRows.set(url,response.clone());},async match(url){return cacheRows.get(url)?.clone();}};
function setup(fetcher,cacheFail=false){const requests=[],imageReads=[],events={};const context={window:{caches:{open:async()=>{if(cacheFail)throw Error('Storage disabled');return cache;}},NativeRadar:{decode(buffer){return JSON.parse(new TextDecoder().decode(buffer));}}},document:{hidden:false,addEventListener(name,fn){events[name]=fn;}},Date,Number,Map,Set,JSON,Promise,Response,Error,Image:class{set src(v){this._src=v;imageReads.push(v);}get src(){return this._src;}decode(){return Promise.resolve();}},fetch:async(url,options)=>{requests.push(url);return fetcher(url,options);}};vm.runInNewContext(code,context);return{api:context.window.WeatherPrepared,requests,imageReads,context};}
const flush=()=>new Promise(r=>setImmediate(r));
(async()=>{
 cacheRows.clear();let release;const blocked=new Promise(r=>release=r);const a=setup(()=>blocked);
 const first=a.api.read('/api/station-plots'),second=a.api.read('/api/station-plots');assert.equal(a.requests.length,1,'in-flight API reads deduplicate');release(new Response(JSON.stringify({history:[{hour:'current'}]})));await Promise.all([first,second]);await a.api.read('/api/station-plots');assert.equal(a.requests.length,1,'prefetched manifest is reused');await flush();
 let fresh;const pending=new Promise(r=>fresh=r);const b=setup(()=>pending);let received;b.api.subscribe('/api/station-plots',d=>received=d);
 const saved=await b.api.read('/api/station-plots');assert.equal(saved._savedCopy,true,'repeat visit can paint a saved copy before network completes');assert.equal(received,undefined);
 fresh(new Response(JSON.stringify({history:[{hour:'new'}]})));await flush();assert.equal(received.history[0].hour,'new');assert.equal(received._savedCopy,undefined,'network update is no longer marked saved');
 const c=setup(()=>Promise.reject(Error('Offline')));const retained=await c.api.read('/api/station-plots');assert.equal(retained._savedCopy,true);await flush();
 await assert.rejects(c.api.read('/api/unknown'),/Unknown prepared/);
 const noStorage=setup(()=>Promise.resolve(new Response(JSON.stringify({periods:['forecast']}))),true);assert.equal((await noStorage.api.read('/api/forecast')).periods[0],'forecast');
 cacheRows.clear();
 const manifests={frames:[{id:'one',url:'/api/prepared/old.bin'},{id:'two',url:'/api/prepared/new.bin'}],site:'KMPX'};
 const warm=setup(async url=>{
  if(url.startsWith('/api/prepared/'))return new Response(JSON.stringify({meta:{site:'KMPX',id:url.includes('new')?'two':'one'}}));
  return new Response(JSON.stringify(url.includes('radar')?manifests:url.includes('satellite')?{frames:[{url:'/api/prepared/sat.jpg'}]}:{history:[],frames:[]}));
 });
 await warm.api.prime();for(let i=0;i<8;i++)await flush();
 assert.ok(warm.requests.includes('/api/forecast')&&warm.requests.includes('/api/air-quality')&&warm.requests.includes('/api/satellite/ntmicro'),'all pages start loading ahead of a tab click');
 assert.equal(warm.requests.filter(u=>u==='/api/prepared/new.bin').length,1);
 const before=warm.requests.length;await warm.api.radar(manifests.frames[1],manifests);assert.equal(warm.requests.length,before,'tab reuses the predecoded newest radar scan');
 assert.ok(warm.imageReads.includes('/api/prepared/sat.jpg'));
 console.log('Prepared data checks passed: shared requests, persistent saved snapshots, fresh subscriptions, failure retention, disabled storage fallback, preloading and decoded radar reuse.');
})().catch(e=>{console.error(e);process.exitCode=1;});
