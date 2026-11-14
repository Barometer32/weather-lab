'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const now=Date.parse('2026-11-14T15:18:00Z');
class TestDate extends Date {constructor(...args){super(...(args.length?args:[now]));}static now(){return now;}}
class Element {
 constructor(){this.textContent='';this.children=[];this.events={};this.hidden=false;}
 append(child){this.children.push(child);}
 replaceChildren(){this.children=[];}
 addEventListener(name,fn){this.events[name]=fn;}
}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
const intervals=[],requests=[],sunPoints=[];
let subscribed,fail=false;
const sample={analysisTime:'2026-11-14T15:00:00Z',checkedAt:'2026-11-14T15:17:00Z',mean:{tempF:35.1,dewpointF:22.4,wind:{speedMph:7.3,direction:355}},stations:[
 {station:'KMIC',lat:45.0623,lon:-93.35108},
 {station:'KMSP',lat:44.88523,lon:-93.23132},
 {station:'KFCM',lat:44.83215,lon:-93.47049}].map(s=>({...s,name:s.station,analysisTime:'2026-11-14T15:00:00Z',tempF:35.1,dewpointF:22.4,wind:{speedMph:7.3,direction:355},gridLat:s.lat,gridLon:s.lon,gridDistanceKm:1}))};
const context={window:{WeatherPrepared:{async read(url,options){requests.push({url,options});if(fail)throw Error('Source check failed.');return structuredClone(sample);},subscribe(url,fn){assert.equal(url,'/api/observations/rtma');subscribed=fn;}},WeatherSun:{elevation(date,lat,lon){assert.equal(date.getTime(),now);sunPoints.push([lat,lon]);return 26.6;}}},document:{hidden:false,getElementById:get,createElement:()=>new Element()},Date:TestDate,Intl,Math,Number,setInterval:(fn,ms)=>intervals.push({fn,ms})};
vm.runInNewContext(fs.readFileSync('static/rtma-observations.js','utf8'),context);
const flush=()=>new Promise(r=>setImmediate(r));
(async()=>{
 const api=context.window.WeatherRTMA;
 api.select('metar');await flush();assert.equal(requests.length,0);
 api.select('observations');await flush();
 assert.equal(get('rtma-temp').textContent,'35°F');assert.equal(get('rtma-dewpoint').textContent,'22°F');
 assert.equal(get('rtma-wind').textContent,'N 7 mph');assert.equal(get('rtma-sun').textContent,'27°');
 assert.match(get('rtma-time').textContent,/9:00 AM CST · 18 min old/);
 assert.equal(get('rtma-stations').children.length,3);
 assert.equal(get('rtma-stations').children[0].children[4].textContent,'N 7 mph');
 assert.equal(new Set(sunPoints.map(point=>point.join(','))).size,3);
 for(const [direction,label] of [[0,'N'],[45,'NE'],[90,'E'],[135,'SE'],[180,'S'],[225,'SW'],[270,'W'],[315,'NW'],[359,'N']])assert.equal(api.wind({speedMph:6.8,direction}),`${label} 7 mph`);
 assert.equal(api.wind({speedMph:.1,direction:0}),'Calm');assert.equal(api.wind({speedMph:5,direction:null}),'Variable 5 mph');
 const stamp=get('rtma-time').textContent;fail=true;await api.refresh(true);
 assert.equal(get('rtma-temp').textContent,'35°F');assert.equal(get('rtma-time').textContent,stamp);
 assert.match(get('rtma-status').textContent,/previous analysis and its original time/);
 fail=false;subscribed({...sample,analysisTime:'2026-11-14T14:15:00Z'});
 assert.match(get('rtma-status').textContent,/NOAA analysis updates are delayed/);
 subscribed({...sample,checkedAt:'2026-11-14T15:00:00Z'});
 assert.match(get('rtma-status').textContent,/Background checks are delayed/);
 const poll=intervals.find(item=>item.ms===15000);assert.ok(poll);
 const before=requests.length;get('observations').hidden=true;poll.fn();await flush();assert.equal(requests.length,before);
 get('observations').hidden=false;poll.fn();await flush();assert.equal(requests.length,before+1);assert.equal(requests.at(-1).options.force,true);
 console.log('RTMA UI passed: rounding, eight directions, three-point current sun, source timestamps, failure retention and visible-only 15-second refresh.');
})().catch(error=>{console.error(error);process.exitCode=1;});
