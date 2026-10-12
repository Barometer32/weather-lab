'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();
const get=id=>{if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,replaceChildren(){},querySelectorAll(){return[];}});return elements.get(id);};
let now='2026-10-12T15:40:00Z',timer,fetches=0;
class Clock extends Date {constructor(...args){super(...(args.length?args:[now]));}}
let current={hour:'2026-10-12T15:00:00Z',available:true,tempF:76.3,dewpointF:54.3,wind:{speedMph:5,direction:350},oldestObservedAt:'2026-10-12T14:53:00Z',newestObservedAt:'2026-10-12T14:53:00Z',missingStations:[]};
const context={document:{getElementById:get,hidden:false},Intl,Date:Clock,Math,fetch:async()=>{fetches++;return {ok:true,json:async()=>({current,history:[],stale:false})};},clearTimeout(){},setTimeout:(callback,delay)=>{timer={callback,delay};return 1;}};
const source=fs.readFileSync('static/app.js','utf8');
vm.runInNewContext(source.slice(0,source.indexOf('function sun()')),context);
(async()=>{
 get('initial-observations').textContent=JSON.stringify({current,history:[],stale:false});
 vm.runInNewContext('initializeObservations()',context);
 assert.equal(fetches,0);
 assert.equal(get('temperature').textContent,'76°F');
 await vm.runInNewContext('loadObservations()',context);
 assert.match(get('updated').textContent,/10:00 AM CDT hourly observation/);
 assert.ok(!get('updated').textContent.includes('METAR'));
 assert.equal(get('temperature').textContent,'76°F');
 assert.equal(get('observation-status').hidden,true);
 current={...current,available:false,tempF:null,dewpointF:null,wind:{speedMph:null,direction:null},oldestObservedAt:null,newestObservedAt:null,missingStations:['KMSP']};
 await vm.runInNewContext('loadObservations()',context);
 assert.equal(get('temperature').textContent,'—');
 assert.match(get('observation-status').textContent,/waiting for a routine report near :53 from KMSP/);
 for(const [stamp,next] of [
 ['2026-10-12T15:40:00Z','2026-10-12T16:00:30Z'],
 ['2026-10-12T15:55:31Z','2026-10-12T16:00:30Z'],
 ['2026-10-12T15:58:31Z','2026-10-12T16:00:30Z'],
 ['2026-10-12T23:58:31Z','2026-10-13T00:00:30Z']
 ]){now=stamp;vm.runInNewContext('scheduleObservations()',context);assert.equal(timer.delay,Date.parse(next)-Date.parse(stamp));}
 assert.ok(!source.includes('setInterval(()=>{if(!document.hidden&&!$("observations").hidden)loadObservations();},60000)'));
 console.log('Hourly-observation UI checks passed: immediate startup hydration without a request, simple hour labels, missing-station QA, :00 scheduling and midnight rollover.');
})().catch(error=>{console.error(error);process.exitCode=1;});
