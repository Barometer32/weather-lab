'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),events=[],reads=[];let fail=false,subscriber,clock=Date.UTC(2026,9,31,3,0);
const element=()=>({events:{},children:[],textContent:'',hidden:false,disabled:false,open:false,addEventListener(k,v){this.events[k]=v;},append(...v){this.children.push(...v);},replaceChildren(){this.children=[];}});
const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
const c={tempF:52.45,dewpointF:40.11,wind:{speedMph:5.6,direction:225},observedAt:'2026-10-31T02:40:00Z'};
let data={version:'hennepin-selected-twelve-v1',current:c,candidate:{stations:[{station:'HPN20',displayName:'Hopkins',time:c.observedAt,tempF:52,dewpointF:40,wind:c.wind,includedFields:['tempF','dewpointF','wind'],reasons:{}}]},sourceFailures:[],serverTime:'2026-10-31T03:00:00Z',checkedAt:'2026-10-31T03:00:00Z'};
class Clock extends Date{constructor(...v){super(...(v.length?v:[clock]));}static now(){return clock;}}
const context={window:{WeatherPrepared:{subscribe(url,fn){assert.equal(url,'/api/hennepin-current');subscriber=fn;},async read(url,options){reads.push([url,options]);if(fail)throw Error('Offline');return data;}},WeatherSun:{sync(){}}},document:{getElementById:get,createElement:element,hidden:false},Intl,Date:Clock,Math,Number,Set,Object,setInterval(fn,ms){events.push({fn,ms});}};
vm.runInNewContext(fs.readFileSync('static/hennepin-current.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 context.window.WeatherHennepinCurrent.select('current');await flush();
 assert.equal(get('current-temp').textContent,'52.5°F');assert.equal(get('current-dew').textContent,'40.1°F');assert.equal(get('current-wind').textContent,'SW 6');
 assert.match(get('current-time').textContent,/9:40 PM CDT/);assert.ok(get('current-notice').hidden);assert.equal(get('current-station-rows').children.length,0);
 get('current-details').open=true;get('current-details').events.toggle();assert.equal(get('current-station-rows').children.length,1);
 assert.equal(get('current-station-rows').children[0].children[4].textContent,'SW 6');
 data={...data,current:{...c,wind:{speedMph:0,direction:null}}};subscriber(data);assert.equal(get('current-wind').textContent,'0');
 data={...data,current:{...c,wind:{speedMph:5,direction:null}}};subscriber(data);assert.equal(get('current-wind').textContent,'VRB 5');
 clock+=40*60000;events[0].fn();await flush();assert.match(get('current-notice').textContent,/Updates delayed/);
 const before=get('current-temp').textContent;fail=true;await get('refresh-current').events.click();assert.equal(get('current-temp').textContent,before);assert.match(get('current-notice').textContent,/last usable average/);
 get('current').hidden=true;const n=reads.length;events[0].fn();await flush();assert.equal(reads.length,n);
 assert.equal(events[0].ms,30000);assert.ok(reads.every(([url])=>url==='/api/hennepin-current'),'Browser reads saved averages only');
 console.log('Current UI passed: Fahrenheit tenths, eight directions, calm 0, station wind details, Chicago observation time, delayed data and failed-read retention.');
})().catch(e=>{console.error(e);process.exitCode=1;});
