'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();
const get=id=>{if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,replaceChildren(){},querySelectorAll(){return[];}});return elements.get(id);};
let now='2026-10-12T15:40:00Z',timer;
class Clock extends Date {constructor(...args){super(...(args.length?args:[now]));}}
let current={hour:'2026-10-12T15:00:00Z',available:true,tempF:76.3,dewpointF:54.3,wind:{speedMph:5,direction:350},oldestObservedAt:'2026-10-12T14:53:00Z',newestObservedAt:'2026-10-12T14:53:00Z',missingStations:[]};
const context={document:{getElementById:get,hidden:false},Intl,Date:Clock,Math,fetch:async()=>({ok:true,json:async()=>({current,history:[],stale:false})}),clearTimeout(){},setTimeout:(callback,delay)=>{timer={callback,delay};return 1;}};
const source=fs.readFileSync('static/app.js','utf8');
vm.runInNewContext(source.slice(0,source.indexOf('function sun()')),context);
(async()=>{
 await vm.runInNewContext('loadObservations()',context);
 assert.match(get('updated').textContent,/10:00 AM CDT hourly observation/);
 assert.match(get('updated').textContent,/METAR 9:53 AM/);
 assert.equal(get('temperature').textContent,'76°F');
 assert.equal(get('observation-status').hidden,true);
 current={...current,available:false,tempF:null,dewpointF:null,wind:{speedMph:null,direction:null},oldestObservedAt:null,newestObservedAt:null,missingStations:['KMSP']};
 await vm.runInNewContext('loadObservations()',context);
 assert.equal(get('temperature').textContent,'—');
 assert.match(get('observation-status').textContent,/waiting for a routine report near :53 from KMSP/);
 for(const [stamp,next] of [
 ['2026-10-12T15:40:00Z','2026-10-12T15:55:30Z'],
 ['2026-10-12T15:55:31Z','2026-10-12T15:58:30Z'],
 ['2026-10-12T15:58:31Z','2026-10-12T16:02:30Z'],
 ['2026-10-12T23:58:31Z','2026-10-13T00:02:30Z']
 ]){now=stamp;vm.runInNewContext('scheduleObservations()',context);assert.equal(timer.delay,Date.parse(next)-Date.parse(stamp));}
 assert.ok(!source.includes('setInterval(()=>{if(!document.hidden&&!$("observations").hidden)loadObservations();},60000)'));
 console.log('Hourly-observation UI checks passed: hour labels, report times, missing-station QA, :55/:58/:02 scheduling and midnight rollover.');
})().catch(error=>{console.error(error);process.exitCode=1;});
