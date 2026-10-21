'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function element(){return {textContent:'',children:[],events:{},hidden:false,disabled:false,
 append(...children){this.children.push(...children);},replaceChildren(){this.children=[];},
 addEventListener(k,f){this.events[k]=f;}};}
const elements=new Map(),get=id=>{assert.notEqual(id,'history','Current must never render history');if(!elements.has(id))elements.set(id,element());return elements.get(id);};
let clock=Date.UTC(2026,9,21,4,0),intervals=[],reads=[],fail=false,syncs=[];
class ClockDate extends Date{constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;}}
const stations=['KFCM','KMIC','KMSP'].map(code=>({code,observedAt:'2026-10-21T03:55:00Z',available:true,tempC:12,dewpointC:5}));
const row={observedAt:'2026-10-21T03:55:00Z',tempF:53.6,dewpointF:41.0,wind:{speedMph:11.5,direction:0},stations};
let data={current:row,candidate:{...row,missingStations:[],staleStations:[],invalidStations:[]},checkedAt:'2026-10-21T04:00:00Z',serverTime:'2026-10-21T04:00:00Z',sourceFailures:[],held:false};
get('initial-current-data').textContent=JSON.stringify(data);
const events={};
const context={window:{WeatherSun:{sync:(...args)=>syncs.push(args)}},document:{getElementById:get,createElement:element,hidden:false,addEventListener:(e,f)=>events[e]=f},Intl,Date:ClockDate,Math,
 setInterval(callback,delay){intervals.push({callback,delay});},
 fetch:async url=>{reads.push(url);if(fail)throw Error('Network unavailable');return {ok:true,json:async()=>data};}};
vm.runInNewContext(fs.readFileSync('static/current-views.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 context.window.WeatherCurrentViews.select('current');await flush();
 assert.equal(reads.length,0,'saved seed paints without a startup source fetch');
 assert.equal(get('temperature').textContent,'53.6°F');assert.equal(get('dewpoint').textContent,'41.0°F');
 assert.equal(get('wind').textContent,'N · 11.5 mph');assert.equal(get('current-stations').children.length,3);
 assert.match(get('updated').textContent,/10:55:00 PM CDT/);assert.doesNotMatch(get('updated').textContent,/held/);
 assert.ok(syncs.length===1);assert.deepEqual(intervals.map(i=>i.delay),[30000,10000]);
 clock+=30000;intervals[0].callback();await flush();assert.equal(reads.length,1);
 get('current').hidden=true;intervals[0].callback();await flush();assert.equal(reads.length,1,'hidden panel does not poll');
 get('current').hidden=false;context.document.hidden=true;intervals[0].callback();await flush();assert.equal(reads.length,1,'hidden browser does not poll');
 context.document.hidden=false;events.visibilitychange();await flush();assert.equal(reads.length,2);
 // No new source check: locally flag an expired airport report, keeping values/time.
 clock=Date.UTC(2026,9,21,4,11);intervals[1].callback();
 assert.match(get('observation-status').textContent,/Held.*15 minutes.*KFCM/);
 assert.match(get('updated').textContent,/10:55:00 PM CDT · held/);
 assert.equal(get('temperature').textContent,'53.6°F');
 fail=true;get('refresh-observations').events.click();await flush();
 assert.equal(get('temperature').textContent,'53.6°F');assert.match(get('observation-status').textContent,/Network unavailable/);
 assert.equal(get('refresh-observations').disabled,false);
 fail=false;data={...data,serverTime:new ClockDate().toISOString(),checkedAt:new ClockDate().toISOString(),held:true,candidate:{...data.candidate,invalidStations:['KMIC']}};
 get('refresh-observations').events.click();await flush();assert.match(get('observation-status').textContent,/quality check failed: KMIC/);
 data={...data,current:null,held:false,candidate:{stations:[],missingStations:['KMIC'],staleStations:[],invalidStations:[]}};
 get('refresh-observations').events.click();await flush();assert.equal(get('temperature').textContent,'—');assert.match(get('observation-status').textContent,/No complete fresh average.*KMIC/);
 assert.ok(reads.every(url=>url==='/api/observations'));
 console.log('Current checks passed: four readings, saved seed, 30-second reads, hidden tabs, strict age hold, original timestamp and source failures.');
})().catch(error=>{console.error(error);process.exitCode=1;});
