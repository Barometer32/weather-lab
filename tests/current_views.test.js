'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function element(){return {textContent:'',children:[],events:{},hidden:false,disabled:false,
 append(...children){this.children.push(...children);},replaceChildren(){this.children=[];},
 setAttribute(k,v){this[k]=v;},addEventListener(k,f){this.events[k]=f;},
 querySelectorAll(){const result=[];const walk=n=>{if(n.className?.includes('qa-dot'))result.push(n);n.children?.forEach(walk);};this.children.forEach(walk);return result;}};}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
let clock=Date.UTC(2026,9,20,12,1),timers=[],reads=[],fail=false;
class ClockDate extends Date{constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;}}
const qa={allStationsUsed:true,stationsUsed:3,checks:{temperature:3,dewpoint:3,wind:3}};
const row={hour:'2026-10-20T12:00:00Z',tempF:68.5,dewpointF:50.5,wind:{speedMph:11.5,direction:0},qa};
let data={current:{...row,available:true},history:Array.from({length:12},(_,i)=>({...row,hour:new Date(Date.UTC(2026,9,20,12-i)).toISOString()})),checkedAt:'2026-10-20T11:02:00Z',stale:false};
get('initial-current-data').textContent=JSON.stringify(data);
const context={window:{},document:{getElementById:get,createElement:element,hidden:false},Intl,Date:ClockDate,Math,
 clearTimeout(id){if(id)id.cancelled=true;},setTimeout(callback,delay){const t={callback,delay};timers.push(t);return t;},
 fetch:async url=>{reads.push(url);if(fail)throw Error('Network unavailable');return {ok:true,json:async()=>data};}};
vm.runInNewContext(fs.readFileSync('static/current-views.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 context.window.WeatherCurrentViews.select('current');await flush();
 assert.equal(reads.length,0,'prepared seed paints without a startup fetch');
 assert.equal(get('temperature').textContent,'69°F');assert.equal(get('wind').textContent,'N 12 mph');
 assert.equal(get('history').children.length,12);assert.equal(get('observation-status').hidden,true);
 assert.equal(timers.at(-1).delay,90000,'scheduled read at :02:30');
 clock=Date.UTC(2026,9,20,12,2,30);timers.at(-1).callback();await flush();
 assert.equal(reads.length,1);assert.ok(timers.some(t=>t.delay===60000&&!t.cancelled));
 data={...data,checkedAt:'2026-10-20T12:02:00Z'};
 const retry=timers.findLast(t=>t.delay===60000&&!t.cancelled);retry.callback();await flush();
 assert.equal(reads.length,2);assert.ok(retry.cancelled,'successful prepared result ends retry');
 get('current').hidden=true;clock=Date.UTC(2026,9,20,13,2,30);
 timers.findLast(t=>t.delay>60000&&!t.cancelled).callback();await flush();assert.equal(reads.length,2,'hidden Current does not poll');
 get('current').hidden=false;context.window.WeatherCurrentViews.select('current');await flush();assert.equal(reads.length,3);
 fail=true;get('refresh-observations').events.click();await flush();
 assert.equal(get('temperature').textContent,'69°F','failed refresh retains prior readings');
 assert.equal(get('history').querySelectorAll().length,12);assert.ok(get('history').querySelectorAll().every(d=>d.className==='qa-dot incomplete'));
 assert.match(get('observation-status').textContent,/Network unavailable/);assert.equal(get('refresh-observations').disabled,false);
 fail=false;data={...data,current:{...row,available:false,tempF:null,dewpointF:null,wind:{speedMph:null},missingStations:['KMIC']},stale:true};
 get('refresh-observations').events.click();await flush();assert.equal(get('temperature').textContent,'—');
 assert.match(get('observation-status').textContent,/KMIC/);assert.match(get('observation-status').textContent,/:02/);
 assert.match(get('observation-status').textContent,/delayed/);
 assert.ok(reads.every(url=>url==='/api/observations'));
 console.log('Current view checks passed: prepared first render, 12-hour history, QA, :02:30 saved-data checks, hidden tab, and refresh failures.');
})().catch(error=>{console.error(error);process.exitCode=1;});
