'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
function start(saved){
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,{events:{},addEventListener(e,f){this.events[e]=f;}});return nodes.get(id);};
 const cache=new Map(saved?[['weather-selected-location-v1',JSON.stringify(saved)]]:[]);let calls=0,success,failure,options,marker,removed=0;
 const queries=[];
 const localStorage={getItem:k=>cache.get(k)||null,setItem:(k,v)=>cache.set(k,v),removeItem:k=>cache.delete(k)};
 const ctx={window:{},document:{getElementById:get},localStorage,navigator:{geolocation:{getCurrentPosition(a,b,c){calls++;success=a;failure=b;options=c;}}},Date,Number,Set,JSON,AbortSignal:{timeout:()=>undefined},fetch:(url,opts)=>new Promise(resolve=>queries.push({url,opts,resolve})),L:{circleMarker(p,opts){marker={p,opts,setLatLng(p){this.p=p;},addTo(){return this;}};return marker;}}};
 vm.runInNewContext(fs.readFileSync('static/location-choice.js','utf8'),ctx);
 return {api:ctx.window.WeatherLocation,get,cache,queries,get calls(){return calls;},get options(){return options;},get marker(){return marker;},get removed(){return removed;},map:{removeLayer(){removed++;}},success(p){success({coords:{latitude:p[0],longitude:p[1],accuracy:100}});},fail(){failure({code:1});},city(index,label,ok=true){queries[index].resolve({ok,json:async()=>({label})});}};
}
const flush=()=>new Promise(setImmediate);
(async()=>{
 const fresh=start();assert.equal(fresh.calls,0);assert.equal(fresh.api.get().selected,false);assert.equal(fresh.queries.length,0);
 fresh.api.radar(fresh.map);assert.equal(fresh.marker,undefined,'No fabricated device-location dot at the default point');
 fresh.get('use-location').events.click();assert.equal(fresh.calls,1);assert.equal(fresh.options.enableHighAccuracy,false);
 fresh.success([44.782,-93.484]);assert.equal(fresh.api.get().latitude,44.782);assert.equal(fresh.marker.opts.radius,3.5);
 assert.equal(fresh.calls,1,'Subscribing maps and displaying selected position do not request location');
 assert.equal(fresh.queries[0].url,'/api/location-name');assert.equal(fresh.queries[0].opts.method,'POST');
 assert.equal(JSON.parse(fresh.queries[0].opts.body).latitude,44.782);
 fresh.city(0,'Shakopee, MN');await flush();assert.equal(fresh.get('current-location').textContent,'Shakopee, MN');
 assert.equal(JSON.parse(fresh.cache.get('weather-selected-location-v1')).label,'Shakopee, MN');
 const restored=start(fresh.api.get());assert.equal(restored.calls,0,'Reload uses the saved selection without accessing device location');assert.equal(restored.queries.length,0,'The saved city avoids repeated lookups');
 restored.api.radar(restored.map);assert.equal(restored.marker.p[0],44.782);
 restored.get('use-location').events.click();restored.fail();assert.equal(restored.api.get().latitude,44.782,'Permission failure retains the prior location');
 restored.get('reset-location').events.click();assert.equal(restored.removed,1);assert.equal(restored.api.get().selected,false);assert.equal(restored.calls,1);
 const older=start({latitude:44.782,longitude:-93.484});assert.equal(older.calls,0);assert.equal(older.queries.length,1,'Previously saved unnamed points need only a name lookup');
 older.city(0,null,false);await flush();assert.match(older.get('current-location').textContent,/city unavailable/);assert.equal(older.api.get().latitude,44.782,'A city-service outage does not discard the weather location');
 older.get('use-location').events.click();older.success([44.98,-93.26]);older.get('reset-location').events.click();older.city(1,'Minneapolis, MN');await flush();
 assert.equal(older.api.get().selected,false);assert.match(older.get('current-location').textContent,/Hopkins/,'A late city response cannot overwrite reset');
 console.log('Location passed: one-shot click only, remembered city, no repeated lookup, permission and name-service failures, async reset and radar dot.');
})().catch(error=>{console.error(error);process.exitCode=1;});
