'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();function get(id){if(!nodes.has(id))nodes.set(id,{hidden:false,disabled:false,textContent:'',events:{},style:{setProperty(){}},setAttribute(k,v){this[k]=v;},addEventListener(k,f){this.events[k]=f;}});return nodes.get(id);}
get('air-quality').hidden=true;get('air-quality-map').hidden=true;
const frame=hour=>({time:`2026-10-24T${String(hour).padStart(2,'0')}:05:00Z`,sourceTime:`2026-10-24T${String(hour-1).padStart(2,'0')}:00:00Z`,url:`/api/prepared/air-quality/mn-region-v1/${hour}.png`});
let data={frames:[frame(1)],stale:false},reads=0,fail=false;const polls=[];
const context={window:{},document:{getElementById:get,hidden:false},Intl,Date,Map,Set,Image:class{decode(){return this.src.includes('bad')?Promise.reject(Error('missing image')):Promise.resolve();}},
 fetch:async url=>{reads++;assert.equal(url,'/api/air-quality');if(fail)throw Error('Unavailable');return{ok:true,json:async()=>data};},setInterval(fn){polls.push(fn);}};
vm.runInNewContext(fs.readFileSync('static/air-quality-views.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 assert.equal(reads,0);get('air-quality').hidden=false;context.window.WeatherAirQuality.select('air-quality');await flush();
 assert.equal(get('air-quality-map').src,frame(1).url);assert.equal(get('air-quality-map').hidden,false);
 assert.equal(get('airq-timeline').disabled,true);assert.match(get('airq-status').textContent,/1\/12.*History is building.*data as of/);
 data={...data,frames:[frame(1),frame(2)]};polls[0]();await flush();assert.equal(get('airq-timeline').value,'1');assert.equal(get('airq-timeline').disabled,false);
 get('airq-timeline').events.input({target:{value:'0'}});await flush();assert.equal(get('air-quality-map').src,frame(1).url);const selected=get('airq-time').textContent;
 data={...data,frames:[frame(1),frame(2),frame(3)]};polls[0]();await flush();assert.equal(get('airq-time').textContent.split(' · ')[0],selected.split(' · ')[0],'refresh preserves selected capture');
 get('airq-timeline').events.input({target:{value:'2'}});await flush();assert.equal(get('air-quality-map').src,frame(3).url);
 const previous=get('air-quality-map').src;fail=true;polls[0]();await flush();assert.equal(get('air-quality-map').src,previous);assert.match(get('airq-status').textContent,/Previous snapshots retained/);
 fail=false;data={...data,frames:[...data.frames,{...frame(4),url:'/bad.png'}]};polls[0]();await flush();assert.equal(get('air-quality-map').src,previous);assert.match(get('airq-status').textContent,/previous image is retained/);
 get('air-quality').hidden=true;const count=reads;polls[0]();await flush();assert.equal(reads,count);
 console.log('Air Q viewer checks passed: fixed prepared images, truthful building history/source times, hourly selection and failed-source/image retention.');
})().catch(error=>{console.error(error);process.exitCode=1;});
