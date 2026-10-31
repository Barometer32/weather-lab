'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let saved=null,blocked=false;
const context={window:{localStorage:{getItem(){if(blocked)throw Error('Unavailable');return saved;},setItem(k,v){if(blocked)throw Error('Unavailable');assert.equal(k,'weather-radar-default-v1');saved=v;}}},Number,Math,JSON,Array};
vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);
vm.runInNewContext(fs.readFileSync('static/default-views.js','utf8'),context);
const model=context.window.WeatherStationModel,views=context.window.WeatherDefaultViews;
const airports=[{station:'KFCM',lat:44.8272,lon:-93.4571},{station:'KMIC',lat:45.0619,lon:-93.3539},{station:'KMSP',lat:44.8831,lon:-93.2289}];
const sites=airports.map(station=>{
 const feet=Array.from({length:12},(_,i)=>model.combinedFootprint({...station,tempF:i===0?-12:53,dewpointF:i===0?-20:38,layers:[{cover:'BKN',baseFtAGL:12000}],wind:{direction:i*30,speedKnots:20}}));
 return{station,f:{left:Math.min(...feet.map(f=>f.left)),right:Math.max(...feet.map(f=>f.right)),top:Math.min(...feet.map(f=>f.top)),bottom:Math.max(...feet.map(f=>f.bottom))}};
});
function project(lat,lon,z){const world=256*2**z,s=Math.sin(lat*Math.PI/180);return{x:(lon+180)/360*world,y:(.5-Math.log((1+s)/(1-s))/(4*Math.PI))*world};}
function boxes(view,size){const center=project(...view.center,view.zoom);return sites.map(({station,f})=>{const p=project(station.lat,station.lon,view.zoom);return{left:p.x-center.x+size.x/2+f.left,right:p.x-center.x+size.x/2+f.right,top:p.y-center.y+size.y/2+f.top,bottom:p.y-center.y+size.y/2+f.bottom};});}
const overlaps=b=>b.some((a,i)=>b.slice(0,i).some(c=>a.left<c.right+2&&a.right>c.left-2&&a.top<c.bottom+2&&a.bottom>c.top-2));
for(const size of [{x:1800,y:720},{x:375,y:560},{x:320,y:400}]){
 const view=views.metar(sites,size),b=boxes(view,size);
 assert.ok(!overlaps(b),'All three reserved station plots clear each other');
 assert.ok(b.every(b=>b.left>=16-1e-7&&b.right<=size.x-16+1e-7&&b.top>=16-1e-7&&b.bottom<=size.y-16+1e-7),'All plots fit in the initial phone/desktop viewport');
 assert.ok(overlaps(boxes({...view,zoom:view.zoom-.25},size)),'Opening view is the widest quarter-level zoom that keeps all three visible');
 assert.equal(view.zoom*4,Math.round(view.zoom*4));
 console.log(`${size.x}x${size.y}: initial zoom ${view.zoom}, all three nonoverlapping`);
}
assert.ok(Number.isFinite(views.metar([],{x:375,y:560}).zoom),'Absent observations still use the three airport locations as the geographic focus');
assert.equal(views.radar().zoom,8);assert.deepEqual(Array.from(views.radar().center),[44.925,-93.462]);
assert.ok(views.saveRadar([44.8,-93.4],8.5));assert.equal(views.radar().zoom,8.5);assert.deepEqual(Array.from(views.radar().center),[44.8,-93.4]);
assert.equal(views.saveRadar([91,0],8),false);assert.equal(views.saveRadar([44,-93],99),false);
saved='not JSON';assert.equal(views.radar().zoom,8);saved='{"center":[0,0],"zoom":null}';assert.equal(views.radar().zoom,8);
blocked=true;assert.equal(views.saveRadar([44,-93],8),false);assert.equal(views.radar().zoom,8);
console.log('Default view checks passed: footprint-aware initial METAR zoom and valid, persistent radar defaults with blocked-storage fallback.');
