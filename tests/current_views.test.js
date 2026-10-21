'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function element(){return {textContent:'',children:[],events:{},hidden:false,disabled:false,
 append(...children){this.children.push(...children);},replaceChildren(){this.children=[];},
 addEventListener(k,f){this.events[k]=f;}};}
const elements=new Map(),get=id=>{assert.ok(!['history','current-checked'].includes(id),'Removed history/source-check UI was accessed');if(!elements.has(id))elements.set(id,element());return elements.get(id);};
let clock=Date.UTC(2026,9,21,4,0),intervals=[],reads=[],fail=false,syncs=[];
class ClockDate extends Date{constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;}}
const stations=['KFCM','KMIC','KMSP'].map(code=>({code,observedAt:'2026-10-21T03:55:00Z',available:true,tempC:12,dewpointC:5,wind:[{speedMph:5.4,direction:225},{speedMph:0,direction:null},{speedMph:7.3,direction:null,variable:true}][['KFCM','KMIC','KMSP'].indexOf(code)]}));
const row={observedAt:'2026-10-21T03:55:00Z',tempF:53.6,dewpointF:41.0,wind:{speedMph:11.5,direction:0},stations};
let data={current:row,candidate:{...row,missingStations:[],outOfSyncStations:[],timeSpreadExceeded:false,invalidStations:[]},checkedAt:'2026-10-21T04:00:00Z',serverTime:'2026-10-21T04:00:00Z',sourceFailures:[],held:false};
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
 assert.equal(get('temperature').textContent,'54°F');assert.equal(get('dewpoint').textContent,'41°F');
 assert.equal(get('wind').textContent,'N 12');assert.equal(get('current-stations').children.length,3);
 assert.deepEqual(get('current-stations').children.map(r=>r.children[4].textContent),['SW 5','Calm','Variable 7']);
 assert.match(get('updated').textContent,/10:55:00 PM CDT/);assert.doesNotMatch(get('updated').textContent,/held/);
 assert.ok(syncs.length===1);assert.deepEqual(intervals.map(i=>i.delay),[30000]);
 assert.equal(get('observation-status').hidden,true);
 clock+=30000;intervals[0].callback();await flush();assert.equal(reads.length,1);
 get('current').hidden=true;intervals[0].callback();await flush();assert.equal(reads.length,1,'hidden panel does not poll');
 get('current').hidden=false;context.document.hidden=true;intervals[0].callback();await flush();assert.equal(reads.length,1,'hidden browser does not poll');
 context.document.hidden=false;events.visibilitychange();await flush();assert.equal(reads.length,2);
 // Wall-clock age alone never disqualifies a coherent set; delayed checks are separate.
 clock=Date.UTC(2026,9,21,4,11);context.window.WeatherCurrentViews.select("current");await flush();
 assert.doesNotMatch(get('observation-status').textContent,/Held|15 minutes old/);
 assert.equal(get('observation-status').hidden,true);
 assert.match(get('updated').textContent,/10:55:00 PM CDT/);assert.doesNotMatch(get('updated').textContent,/held/);
 assert.equal(get('temperature').textContent,'54°F');
 fail=true;get('refresh-observations').events.click();await flush();
 assert.equal(get('temperature').textContent,'54°F');assert.match(get('observation-status').textContent,/Network unavailable/);
 assert.equal(get('refresh-observations').disabled,false);
 fail=false;data={...data,serverTime:new ClockDate().toISOString(),checkedAt:new ClockDate().toISOString(),held:true,candidate:{...data.candidate,invalidStations:['KMIC']}};
 get('refresh-observations').events.click();await flush();assert.equal(get('observation-status').hidden,true);
 data={...data,candidate:{...data.candidate,invalidStations:[],timeSpreadExceeded:true,timestampSpreadSeconds:1200,outOfSyncStations:['KFCM']}};
 get('refresh-observations').events.click();await flush();assert.equal(get('observation-status').hidden,true);
 assert.match(get('updated').textContent,/10:55:00 PM CDT/);
 data={...data,current:null,held:false,candidate:{stations:[],missingStations:['KMIC'],outOfSyncStations:[],timeSpreadExceeded:false,invalidStations:[]}};
 get('refresh-observations').events.click();await flush();assert.equal(get('temperature').textContent,'—');assert.match(get('observation-status').textContent,/Waiting for a complete MADIS five-minute average/);
 for(const [degrees,expected] of [[0,'N'],[45,'NE'],[90,'E'],[135,'SE'],[180,'S'],[202,'S'],[203,'SW'],[225,'SW'],[270,'W'],[315,'NW'],[359,'N']]){
   data={...data,current:{...row,wind:{speedMph:5.4,direction:degrees}},held:false};
   get('refresh-observations').events.click();await flush();assert.equal(get('wind').textContent,expected+' 5');
 }
 assert.ok(reads.every(url=>url==='/api/observations'));
 console.log('Current checks passed: four readings, saved seed, 30-second reads, hidden tabs, relative timestamp hold, original timestamp and source failures.');
})().catch(error=>{console.error(error);process.exitCode=1;});
