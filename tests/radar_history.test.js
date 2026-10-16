'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),drawn=[],downloads=[],deferred=new Map();
function node(){return {hidden:false,disabled:false,events:{},style:{setProperty(){}},textContent:'',classList:{contains(){return false;},add(){},remove(){}},setAttribute(k,v){this[k]=v;},append(){},replaceChildren(){},addEventListener(k,f){this.events[k]=f;},focus(){}};}
function get(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}
const base=Date.UTC(2026,9,15,0),frames=Array.from({length:121},(_,i)=>({id:String(i),time:new Date(base+i*60000).toISOString(),url:'/scan/'+i}));
let manifest={frames,site:'KMPX',renderVersion:'v2',palette:[{dbz:10,color:'#008800'},{dbz:80,color:'#ffffff'}],elevationDegrees:.5,historyHours:2,windowStart:frames[0].time,collectionErrors:0};
const pane={style:{}},layer={addTo(){return this;},on(){return this;}};
const context=vm.createContext({document:{getElementById:get,createElement:node,addEventListener(){},hidden:false,body:{classList:{toggle(){}}}},Intl,Date,Math,Map,Set,Error,Promise,window:{},WeatherCloudViews:{select(){}},setTimeout(){},setInterval(){},clearTimeout(){},
 NativeRadar:{decode:x=>x,layer:()=>({addTo(){return this;},setFrame(data){drawn.push(data.meta.id);}})},
 L:{map(){return {setView(){return this;},createPane(){return pane;},getPane(){return pane;}};},tileLayer:()=>layer},
 fetch:async url=>{
   if(url.startsWith('/api/radar'))return {ok:true,json:async()=>manifest};
   downloads.push(url);const id=url.split('/').at(-1);
   if(deferred.has(id))return new Promise(resolve=>deferred.set(id,()=>resolve({ok:true,arrayBuffer:async()=>({meta:{site:'KMPX',id}})})));
   return {ok:true,arrayBuffer:async()=>({meta:{site:'KMPX',id}})};
 }});
vm.runInContext(fs.readFileSync('static/app.js','utf8'),context);
(async()=>{
 get('radar').hidden=false;
 await context.loadRadar();
 assert.deepEqual(downloads,['/scan/120']);assert.equal(get('timeline').max,'120');
 assert.equal(drawn.at(-1),'120');assert.match(get('radar-status').textContent,/Past 2 hours/);
 for(let i=0;i<30;i++)await context.showFrame(i);
 assert.ok(vm.runInContext('radarLayers.size',context)<=24);
 assert.equal(drawn.at(-1),'29');
 const count=downloads.length;await context.showFrame(29);assert.equal(downloads.length,count);
 deferred.set('31',null);const old=context.showFrame(31);await Promise.resolve();
 await context.showFrame(32);deferred.get('31')();await old;
 assert.equal(drawn.at(-1),'32');assert.equal(get('timeline').value,'32');
 const selected=get('radar-time').textContent;await context.loadRadar();
 assert.equal(get('timeline').value,'32');assert.equal(get('radar-time').textContent,selected);
 assert.equal(get('timeline').disabled,false);
 console.log('Radar history checks passed: 121-scan timeline, one initial scan fetch, 24-scan memory bound, cached scrubbing, preserved time and stale-response protection.');
})().catch(e=>{console.error(e);process.exitCode=1;});
