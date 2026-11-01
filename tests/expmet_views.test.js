'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),shown=new Map(),events={};let subscriber,reads=0,full;
function get(id){if(!nodes.has(id))nodes.set(id,{hidden:false,children:[],events:{},style:{},append(...v){this.children.push(...v);},setAttribute(){},addEventListener(k,fn){this.events[k]=fn;}});return nodes.get(id);}
const point=(gx,gy)=>({station:`GRID:${gx}:${gy}`,gx,gy,lat:45+gy*10/111.195,lon:-93+gx*10/(111.195*Math.cos(Math.PI/4)),tempF:55,dewpointF:45,wind:{speedMph:12,speedKnots:10.43,direction:350},support:{temperature:5},nearestKm:{temperature:4},ageMinutes:{temperature:10}});
let data={analysisTime:'2026-11-01T15:00:00Z',checkedAt:'2026-11-01T15:05:00Z',gridKm:10,stationCount:10,providers:{'Airport METAR':3},sources:{madis:true,airports:true},stations:[point(0,0),point(1,0),point(0,1)]};
const map={setView(){return this;},getSize(){return{x:1200,y:900};},on(k,fn){events[k]=fn;},latLngToContainerPoint([lat,lon]){return{x:500+(lon+93)*1000,y:500-(lat-45)*1000};},invalidateSize(){}};
const context={window:{WeatherPrepared:{read:async()=>{reads++;return data;},subscribe(url,fn){assert.equal(url,'/api/expmet');subscriber=fn;}},WeatherFullscreen:{attach(c){full=c;}},addEventListener(){},localStorage:{getItem(){return null;}}},document:{getElementById:get,createElement:()=>({children:[],append(n){this.children.push(n);}}),hidden:false},Intl,Math,Number,Date,Map,Set,setTimeout(){},setInterval(){},L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>({addTo(){return this;},removeLayer(m){shown.delete(m.id);}}),divIcon:x=>x,marker:(position,options)=>({id:position.join(','),position,...options,bindPopup(p){this.popup=p;return this;},addTo(){shown.set(this.id,this);return this;},setIcon(i){this.icon=i;return this;},setPopupContent(p){this.popup=p;return this;}})}};
for(const file of ['static/metar-model.js','static/expmet-views.js'])vm.runInNewContext(fs.readFileSync(file,'utf8'),context);
(async()=>{
 context.window.WeatherExpmet.select('expmet');await new Promise(setImmediate);
 assert.equal(reads,1);assert.equal(shown.size,3);assert.equal(full.surfaceId,'expmet-surface');
 const first=[...shown.values()][0];assert.match(first.icon.html,/wind-barb/);assert.match(first.icon.html,/plot-temp/);assert.doesNotMatch(first.icon.html,/plot-ceiling|plot-sky/);
 assert.match(get('expmet-time').textContent,/Analysis/);assert.match(get('expmet-status').textContent,/3 airports \+ 7 public MADIS/);
 get('expmet-product').events.change({target:{value:'temperature'}});assert.match(first.icon.html,/plot-temp/);assert.doesNotMatch(first.icon.html,/wind-barb|plot-dew/);
 get('expmet-product').events.change({target:{value:'wind'}});assert.match(first.icon.html,/wind-barb/);assert.doesNotMatch(first.icon.html,/plot-temp|plot-dew/);
 assert.equal(reads,1,'Switching fields does not download or process observations');
 data={...data,checkedAt:'2026-11-01T16:05:00Z',analysisTime:'2026-11-01T16:00:00Z',stale:true,sources:{airports:true,madis:false}};subscriber(data);
 assert.match(get('expmet-status').textContent,/MADIS unavailable/);assert.match(get('expmet-time').textContent,/delayed/);
 console.log('EXPMET viewer passed: regular estimated points, four field modes, source visibility, stale labels, fullscreen and no source collection.');
})().catch(e=>{console.error(e);process.exitCode=1;});
