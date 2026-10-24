'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function element(){return{value:'',children:[],events:{},hidden:false,disabled:false,textContent:'',classList:{add(){}},setAttribute(k,v){this[k]=v;},append(...v){this.children.push(...v);},replaceChildren(){this.children=[];},addEventListener(k,f){this.events[k]=f;}};}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
const intervals=[];let reads=0,failed=false;
const stations=[{station:'HPN20',displayName:'Hopkins',network:'Hennepin West',time:'2026-10-24T18:03:00Z',tempF:71.4,dewpointF:50.6,wind:{speedMph:7.4,direction:222.5}},{station:'HPN24',displayName:'Edina',network:'Hennepin West',time:'2026-10-24T17:53:00Z',tempF:null,dewpointF:49,wind:{speedMph:0,direction:null}}];
const data={stations,networks:['Hennepin West'],serverTime:'2026-10-24T18:23:00Z',checkedAt:'2026-10-24T18:23:00Z',sourceFailures:[],collectorDelayed:false,average:null};
const context={document:{getElementById:get,createElement:element,hidden:false},window:{WeatherSun:{sync(){}}},Intl,Date,Number,Math,setInterval(callback,delay){intervals.push({callback,delay});},fetch:async url=>{assert.equal(url,'/api/observation-stations');reads++;if(failed)throw Error('Source unavailable');return{ok:true,json:async()=>data};}};
vm.runInNewContext(fs.readFileSync('static/observation-views.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 assert.equal(reads,0);context.window.WeatherObservations.select('observations');await flush();
 assert.equal(reads,1);assert.equal(get('observations-rows').children.length,2);
 const [first,second]=get('observations-rows').children;
 assert.equal(first.children[0].children[0].textContent,'Hopkins');
 assert.equal(first.children[0].children[1].textContent,'HPN20');
 assert.equal(first.children[1].children[1].textContent,'20 min old');
 assert.equal(first.children[2].textContent,'71.4°');assert.equal(first.children[4].textContent,'SW 7');
 assert.equal(second.children[2].textContent,'—');assert.equal(second.children[4].textContent,'0');
 get('observations-search').value='hopkins';get('observations-search').events.input();assert.equal(get('observations-rows').children.length,1);
 get('observations-search').value='HPN24';get('observations-search').events.input();assert.equal(get('observations-rows').children[0].children[0].children[0].textContent,'Edina');
 get('refresh-observations').events.click();await flush();assert.equal(get('observations-search').value,'HPN24','refresh preserves station search');
 failed=true;get('refresh-observations').events.click();await flush();assert.equal(get('observations-rows').children.length,1);assert.match(get('observations-status').textContent,/Previous readings retained/);
 assert.equal(intervals[0].delay,120000);get('observations').hidden=true;const before=reads;intervals[0].callback();await flush();assert.equal(reads,before);
 get('observations').hidden=false;context.document.hidden=true;intervals[0].callback();await flush();assert.equal(reads,before);
 console.log('Observation list checks passed: station identity, source time/age, missing fields, calm wind, search, Hennepin West sites, failed-refresh retention and two-minute reads.');
})().catch(error=>{console.error(error);process.exitCode=1;});
