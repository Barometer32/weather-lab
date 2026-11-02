'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(saved=false){
 const events={},storage=new Map(saved?[["weather-radar-location-enabled","true"]]:[]),watches=new Map(),cleared=[],layers=[],pans=[];let next=0;
 const nodes={"radar-location":{events:{},setAttribute(k,v){this[k]=v;},addEventListener(k,v){this.events[k]=v;}},"radar-location-status":{hidden:true}};
 const map={panes:{},createPane(k){this.panes[k]={style:{}};},getPane(k){return this.panes[k];},panTo(p){pans.push(p);},removeLayer(l){const i=layers.indexOf(l);if(i>=0)layers.splice(i,1);}};
 function layer(coords,options){return {coords,options,addTo(){layers.push(this);return this;},bindPopup(p){this.popup=p;return this;},bindTooltip(){return this;},setLatLng(p){this.coords=p;return this;},setPopupContent(p){this.popup=p;return this;},setRadius(v){this.options.radius=v;return this;},bringToFront(){}};}
 const geo={watchPosition(success,error,options){const id=next++;watches.set(id,{success,error,options});return id;},clearWatch(id){cleared.push(id);}};
 const ctx={window:{addEventListener(k,fn){events[k]=fn;}},document:{hidden:false,getElementById:k=>nodes[k],createElement:()=>({}),addEventListener(k,fn){events[k]=fn;}},navigator:{geolocation:geo},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},L:{circleMarker:layer,circle:layer},Date,Number,Math};
 vm.runInNewContext(fs.readFileSync('static/radar-location.js','utf8'),ctx);
 const location=ctx.window.WeatherRadarLocation;location.attach(map);
 const fix=(lat=44.9,lon=-93.4,accuracy=20)=>({coords:{latitude:lat,longitude:lon,accuracy},timestamp:Date.now()});
 return {ctx,nodes,map,location,geo,events,watches,cleared,layers,pans,storage,fix};
}
{
 const t=setup();assert.equal(t.watches.size,0);t.location.select('radar');assert.equal(t.watches.size,0,'No GPS before explicit opt-in');
 t.nodes['radar-location'].events.click();assert.equal(t.watches.size,1);assert.equal(t.watches.get(0).options.maximumAge,30000);t.watches.get(0).success(t.fix());
 assert.equal(t.layers.length,2);assert.equal(t.pans.length,1);assert.equal(t.layers[0].options.radius,5);assert.equal(t.layers[1].options.radius,20);
 t.watches.get(0).success(t.fix(45,-94,30));assert.equal(t.layers.length,2);assert.equal(t.pans.length,1,'Updates move the dot without recentering a panned map');assert.equal(t.layers[1].options.radius,30);
 t.location.select('metar');assert.ok(t.cleared.includes(0),'Watch ID zero is correctly stopped');assert.equal(t.layers.length,0);t.watches.get(0).success(t.fix());assert.equal(t.layers.length,0,'Late fixes cannot restore a canceled marker');
 t.location.select('radar');assert.equal(t.watches.size,2);t.watches.get(1).success(t.fix());assert.equal(t.layers.length,2);
 t.ctx.document.hidden=true;t.events.visibilitychange();assert.ok(t.cleared.includes(1));assert.equal(t.layers.length,0);t.ctx.document.hidden=false;t.events.visibilitychange();assert.equal(t.watches.size,3);
 t.watches.get(2).success(t.fix(45,-94,20000));assert.match(t.nodes['radar-location-status'].textContent,/20 km/);
 t.nodes['radar-location'].events.click();assert.equal(t.storage.get('weather-radar-location-enabled'),'false');assert.equal(t.layers.length,0);
}
{
 const t=setup();t.location.select('radar');t.nodes['radar-location'].events.click();t.watches.get(0).error({code:1});assert.equal(t.nodes['radar-location']['aria-pressed'],'false');assert.match(t.nodes['radar-location-status'].textContent,/denied/);assert.equal(t.layers.length,0);
 t.nodes['radar-location'].events.click();t.watches.get(1).success({...t.fix(),timestamp:Date.now()-180000});assert.equal(t.layers.length,0,'Old positions are not presented as current');
 t.watches.get(1).success(t.fix(NaN));assert.equal(t.layers.length,0);assert.equal(t.nodes['radar-location']['aria-pressed'],'false');
}
{
 const t=setup(true);assert.equal(t.watches.size,0,'Remembered preference does not start GPS on another page');t.location.select('radar');assert.equal(t.watches.size,1);t.watches.get(0).success(t.fix());assert.equal(t.pans.length,0,'Remembered preference preserves saved opening view');
}
const html=fs.readFileSync('static/index.html','utf8');assert.match(html,/<div id="radar-map-area"[\s\S]*id="radar-location"[\s\S]*id="radar-location-status"/);assert.match(html,/radar-location.js\?v=radar-location-v2/);
console.log('Radar location passed: explicit opt-in, updates, accuracy, preserved zoom/view, hidden-tab cleanup, permission failure, stale-fix rejection and fullscreen control.');

const retiredKeys=[];vm.runInNewContext(fs.readFileSync('static/app.js','utf8').split('const $')[0],{localStorage:{removeItem:key=>retiredKeys.push(key)}});assert.deepEqual(retiredKeys,['weather-test-location'],'Only the retired TEST location is cleared; radar preferences remain');
