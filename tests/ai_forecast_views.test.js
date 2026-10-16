'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map(),events={},timers=[],panes=new Map(),pending=new Map();
let shown=[],fetches=[];
function element(){return{value:'',hidden:false,disabled:false,children:[],events:{},style:{setProperty(){}},setAttribute(k,v){this[k]=v;},replaceChildren(){this.children=[];},append(...v){this.children.push(...v);},addEventListener(k,f){this.events[k]=f;}};}
function get(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}
get('ai-field').value='tempF';get('ai-forecast').hidden=true;
const leads=Array.from({length:24},(_,i)=>i+1),issue='2026-10-16T21:00:00Z';
const history=leads.map(lead=>({hour:new Date(Date.parse(issue)+lead*3600000).toISOString(),leadHours:lead,stationCount:25,analysisUrl:`/ai/${lead}.json`}));
const metric={mae:2.345,count:8000};
const report={testStart:'2026-10-01T01:00:00Z',testEnd:'2026-10-16T00:00:00Z',trainedAt:issue,stationCount:25,trainingData:{days:120},modelId:'a'.repeat(16),algorithm:'Boosted trees',limitations:['Surface-only forecast'],scores:leads.map(lead=>({leadHours:lead,forecast:{tempF:metric,dewpointF:metric,wind:metric},persistence:{tempF:{...metric,mae:4},dewpointF:metric,wind:metric},modelWeight:{tempF:.5,dewpointF:lead===1?0:.5,wind:.75}}))};
let dataset={training:{state:'running',stage:'training',percent:50,elapsedSeconds:60,estimatedRemainingSeconds:120,updatedAt:issue,message:'Training +6 h temperature',events:[{percent:50,message:'Training',elapsedSeconds:60}]},model:report,forecast:{history,issueHour:issue,inputSignature:'one',modelId:report.modelId,modelReport:report,latestReportTime:'2026-10-16T20:53:00Z',stale:false}};
const map={fitBounds(){},createPane(n){const p={style:{}};panes.set(n,p);return p;},getPane(n){return panes.get(n);},invalidateSize(){}};
const group={addTo(){return this;},clearLayers(){shown=[];}};
const layer=(kind,value)=>({on(){return this;},addTo(){shown.push({kind,value});return this;}});
const context={window:{},document:{hidden:false,getElementById:get,createElement:element,addEventListener(k,f){events[k]=f;}},Date,Intl,Math,Map,Set,Number,clearTimeout(t){if(t)t.cleared=true;},setTimeout(callback,delay){if(delay===0)return setTimeout(callback,0);const t={callback,delay};timers.push(t);return t;},fetch:async(url,options)=>{fetches.push({url,options});if(url==='/api/ai-forecast')return{ok:true,json:async()=>dataset};return{ok:true,json:()=>new Promise(resolve=>pending.set(url,resolve))};},L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>group,imageOverlay:url=>layer('image',url),geoJSON:geo=>layer('contours',geo),divIcon:x=>x,marker:(_pos,options)=>layer('vector',options)}};
vm.runInNewContext(fs.readFileSync('static/ai-forecast.js','utf8'),context);
const viewer=context.window.WeatherAI,flush=()=>new Promise(resolve=>setImmediate(resolve));
function manifest(i){const f=history[i],base={palette:[[0,'#0f0'],[5,'#ff0'],[10,'#f00'],[15,'#f00']],contours:{type:'FeatureCollection',features:[]},arrows:[],used:25};return{hour:f.hour,leadHours:f.leadHours,bounds:[[39,-108],[51,-80]],fields:{tempF:{...base,imageUrl:`/${f.leadHours}/temp.png`},dewpointF:{...base,imageUrl:`/${f.leadHours}/dew.png`},wind:{...base,imageUrl:`/${f.leadHours}/wind.png`,arrows:[{lat:45,lon:-93,direction:359,speed:12}]}}};}
async function resolve(i){pending.get(history[i].analysisUrl)(manifest(i));await flush();}
const scrub=i=>get('ai-timeline').events.input({target:{value:String(i)}});
(async()=>{
 assert.equal(fetches.length,0);viewer.select('maps');assert.equal(fetches.length,0);
 get('ai-forecast').hidden=false;viewer.select('ai-forecast');await flush();
 assert.equal(get('ai-progress').value,50);assert.match(get('ai-progress-detail').textContent,/About 2 min 0 s left in this stage/);
 assert.equal(get('ai-scores').children.length,24);assert.match(get('ai-scores').children[0].children[2].children[0].textContent,/Unchanged-value fallback/);
 await resolve(0);assert.match(get('ai-time').textContent,/\+1 hours.*FORECAST/);
 assert.ok(timers.some(t=>t.delay===5000));assert.equal(get('ai-timeline').max,'23');
 const scale=get('ai-legend').children[1].style.background;
 get('ai-field').value='dewpointF';get('ai-field').events.change();await flush();
 assert.match(get('ai-map-status').textContent,/Unchanged-value fallback selected by validation/);
 assert.equal(get('ai-legend').children[1].style.background,scale);
 scrub(22);await flush();scrub(23);await flush();await resolve(22);assert.equal(shown.length,0);
 await resolve(23);assert.match(get('ai-time').textContent,/\+24 hours/);assert.equal(shown.find(x=>x.kind==='image').value,'/24/dew.png');
 get('ai-field').value='wind';get('ai-field').events.change();await flush();
 assert.match(shown.find(x=>x.kind==='vector').value.icon.html,/rotate\(179\)/);
 assert.equal(shown.find(x=>x.kind==='vector').value.interactive,false);
 dataset={...dataset,training:{...dataset.training,state:'completed',percent:100},forecast:{...dataset.forecast,stale:true}};
 get('refresh-ai').events.click();await flush();assert.match(get('ai-stage').textContent,/Training complete/);
 assert.match(get('ai-source-status').textContent,/Input update delayed/);assert.ok(timers.some(t=>t.delay===60000));
 get('ai-play').events.click();await flush();assert.equal(get('ai-play')['aria-pressed'],'true');
 viewer.select('maps');assert.equal(get('ai-play')['aria-pressed'],'false');
 assert.ok(!fs.readFileSync('static/ai-forecast.js','utf8').includes('method:"POST"'));
 console.log('AI viewer checks passed: real progress/ETA, held-out scores, 24 hourly future times, fallback disclosure, colors, vectors, race protection, playback and read-only polling.');
})().catch(error=>{console.error(error);process.exitCode=1;});
