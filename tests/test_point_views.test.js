'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),calls=[],stored=new Map();let gps=0,mapClick;
function element(tag='div'){return {tag,children:[],events:{},hidden:false,value:'',append(...x){this.children.push(...x);},replaceChildren(...x){this.children=x;},addEventListener(e,f){this.events[e]=f;},setAttribute(){},style:{}};}
const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};get('test-window').value='60';
function fetch(url){let resolve,reject;const p=new Promise((r,j)=>{resolve=data=>r({ok:true,json:async()=>data});reject=j;});calls.push({url,resolve,reject});return p;}
const layer={addTo(){return this;},setLatLng(){return this;},bindPopup(){return this;}};
const map={setView(){return this;},getZoom(){return 10;},invalidateSize(){},on(event,fn){if(event==='click')mapClick=fn;}};
const ctx={window:{addEventListener(){}},document:{getElementById:get,createElement:element,hidden:false},navigator:{geolocation:{getCurrentPosition(){gps++;}}},localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)},fetch,URLSearchParams,Intl,Date,Number,Math,JSON,Promise,setTimeout:fn=>fn(),setInterval(){},L:{map:()=>map,tileLayer:()=>layer,circleMarker:()=>({...layer}),layerGroup:()=>({addTo(){return this;},clearLayers(){}})}};
vm.runInNewContext(fs.readFileSync('static/test-weather.js','utf8'),ctx);
const tick=()=>new Promise(r=>setImmediate(r));
const conditions=value=>({fields:{temperatureF:{value,stationCount:4},dewpointF:{value:40,stationCount:4},windMph:{value:0,stationCount:4}},available:true,stations:[],stationCount:4,gridSpacingKm:5,checkedAt:'2026-11-02T12:05:00Z',observationStart:'2026-11-02T11:50:00Z',observationEnd:'2026-11-02T12:00:00Z',sourceErrors:[]});
const forecast={periods:[{name:'Tonight',temperature:40,temperatureUnit:'F',detailedForecast:'Clear.'}],timeZone:'America/Chicago',updatedAt:'2026-11-02T11:00:00Z',sourceUrl:'https://forecast.weather.gov/MapClick.php?lat=44.9&lon=-93.4'};
(async()=>{
 ctx.window.WeatherTest.select('metar');assert.equal(calls.length,0);assert.equal(gps,0);
 ctx.window.WeatherTest.select('test');assert.equal(calls.length,2);assert.ok(calls[0].url.includes('conditions'));assert.ok(calls[0].url.includes('minutes=60'));
 calls[0].resolve(conditions(50));calls[1].resolve(forecast);await tick();
 assert.equal(get('test-temp').textContent,'50°F');assert.equal(get('test-wind').textContent,'0');assert.match(get('test-valid').textContent,/Reports/);assert.equal(get('test-periods').children.length,1);
 // A new pin clears old values, and late old-location responses cannot win.
 mapClick({latlng:{lat:45,lng:-94}});const oldCalls=calls.slice(-2);assert.equal(get('test-temp').textContent,'—');
 mapClick({latlng:{lat:46,lng:-95}});const newCalls=calls.slice(-2);
 newCalls[0].resolve(conditions(60));newCalls[1].reject(new Error('Forecast temporarily unavailable'));await tick();
 oldCalls[0].resolve(conditions(80));oldCalls[1].resolve(forecast);await tick();
 assert.equal(get('test-temp').textContent,'60°F');assert.match(get('test-issued').textContent,/temporarily unavailable/);assert.equal(get('test-location').textContent,'46.0000, -95.0000');
 // Leaving during a load must restart it when returning, rather than stay blank.
 get('test-refresh').events.click();const before=calls.length;ctx.window.WeatherTest.select('radar');ctx.window.WeatherTest.select('test');assert.equal(calls.length,before+2);
 get('test-locate').events.click();assert.equal(gps,1,'GPS is only requested by the explicit button');
 console.log('TEST view passed: lazy loading, calm wind, independent forecast failure, location races, clear-on-move, return during loading and explicit GPS.');
})().catch(e=>{console.error(e);process.exitCode=1;});
