'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
function start(saved){
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,{events:{},addEventListener(e,f){this.events[e]=f;}});return nodes.get(id);};
 const cache=new Map(saved?[['weather-selected-location-v1',JSON.stringify(saved)]]:[]);let calls=0,success,failure,options,marker,removed=0;
 const localStorage={getItem:k=>cache.get(k)||null,setItem:(k,v)=>cache.set(k,v),removeItem:k=>cache.delete(k)};
 const ctx={window:{},document:{getElementById:get},localStorage,navigator:{geolocation:{getCurrentPosition(a,b,c){calls++;success=a;failure=b;options=c;}}},Date,Number,Set,JSON,L:{circleMarker(p,opts){marker={p,opts,setLatLng(p){this.p=p;},addTo(){return this;}};return marker;}}};
 vm.runInNewContext(fs.readFileSync('static/location-choice.js','utf8'),ctx);
 return {api:ctx.window.WeatherLocation,get,cache,get calls(){return calls;},get options(){return options;},get marker(){return marker;},get removed(){return removed;},map:{removeLayer(){removed++;}},success(p){success({coords:{latitude:p[0],longitude:p[1],accuracy:100}});},fail(){failure({code:1});}};
}
const fresh=start();assert.equal(fresh.calls,0);assert.equal(fresh.api.get().selected,false);
fresh.api.radar(fresh.map);assert.equal(fresh.marker,undefined,'No fabricated device-location dot at the default point');
fresh.get('use-location').events.click();assert.equal(fresh.calls,1);assert.equal(fresh.options.enableHighAccuracy,false);
fresh.success([44.8,-93.5]);assert.equal(fresh.api.get().latitude,44.8);assert.equal(fresh.marker.opts.radius,3.5);
assert.equal(fresh.calls,1,'Subscribing maps and displaying selected position do not request location');
const restored=start(fresh.api.get());assert.equal(restored.calls,0,'Reload uses the saved selection without accessing device location');
restored.api.radar(restored.map);assert.equal(restored.marker.p[0],44.8);
restored.get('use-location').events.click();restored.fail();assert.equal(restored.api.get().latitude,44.8,'Permission failure retains the prior location');
restored.get('reset-location').events.click();assert.equal(restored.removed,1);assert.equal(restored.api.get().selected,false);assert.equal(restored.calls,1);
console.log('Location passed: click-only single fix, remembered selection, no auto access or watching, permission fallback, small radar dot and reset.');
