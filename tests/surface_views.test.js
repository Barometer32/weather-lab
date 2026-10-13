"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),C=require("../static/surface-core.js");
const html=fs.readFileSync("static/index.html","utf8"),ids=new Set([...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1])),nodes=new Map(),groups=[],jobs=[],reads=[];
function node(){return {value:"",hidden:false,disabled:false,checked:true,open:false,textContent:"",children:[],events:{},style:{setProperty(k,v){this[k]=v;}},classList:{toggle(){}},append(...children){this.children.push(...children);},replaceChildren(...children){this.children=[...children];},setAttribute(k,v){this[k]=v;},addEventListener(k,f){this.events[k]=f;},getContext(){return {createImageData(w,h){return {data:new Uint8ClampedArray(w*h*4)};},putImageData(){}};},toDataURL(){return "data:image/png;base64,test";}};}
function get(id){assert.ok(ids.has(id),"Missing HTML element "+id);if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}
for(const [id,value] of Object.entries({"surface-field":"plots","surface-source":"all","surface-quality":"passed","surface-style":"both","surface-detail":"detail","surface-colors":"weather"}))get(id).value=value;
get("surface").hidden=true;
const map={createPane(){},getPane(){return {style:{}};},setView(){return this;},getSize(){return {x:800,y:580};},invalidateSize(){},on(){},fitBounds(){},removeLayer(){},getBounds(){return {getSouth:()=>44.7,getNorth:()=>45.3,getWest:()=>-93.9,getEast:()=>-93};},latLngToContainerPoint([lat,lon]){return {x:(lon+93.9)/.9*800,y:(45.3-lat)/.6*580};}};
function group(){const g={items:[],addTo(){return this;},clearLayers(){this.items=[];}};groups.push(g);return g;}
function layer(value){return {value,bindPopup(p){this.popup=p;return this;},addTo(g){if(g.items)g.items.push(this);return this;}};}
const L={map:()=>map,tileLayer:()=>layer(),layerGroup:group,divIcon:v=>v,marker:(coords,options)=>layer({coords,options}),polyline:(coords,options)=>layer({coords,options}),imageOverlay:(url,bounds,options)=>layer({url,bounds,options}),popup:()=>({setLatLng(){return this;},setContent(){return this;},openOn(){return this;}})};
const hour="2026-10-13T01:00:00Z",snapshot={version:1,hour,sourceErrors:[],stations:[]};
for(let i=0;i<9;i++){
 const name=["KFCM","KMIC","KMSP","MN001","MN002","CW001","CW002","CW003","CW004"][i],kind=i<3?"airport":i<5?"road":"mesonet",descriptor=i===4?"LOCAL":"V";
 snapshot.stations.push({id:name,station:name,name,kind,network:kind==="road"?"MN_RWIS":"test",time:"2026-10-13T00:53:00Z",lat:44.8+(i%3)*.15,lon:-93.8+Math.floor(i/3)*.3,tempF:60+i*2,dewpointF:50,rh:60,windMph:10,direction:0,uMph:0,vMph:-10,gustMph:15,spreadF:10+i*2,qc:Object.fromEntries(["tempF","dewpointF","rh","windMph","direction","vector","gustMph","spreadF"].map(k=>[k,{accepted:true,descriptor}])),derived:[]});
}
const manifest={version:1,checkedAt:hour,history:Array.from({length:12},(_,i)=>({hour:new Date(Date.parse(hour)-(11-i)*3600000).toISOString(),url:i===11?"/api/prepared/surface/v1/2026101301-aabbccddeeff.json":null}))};
manifest.history[11].hour=hour;
class Worker {
 constructor(){jobs.push(this);}
 terminate(){this.closed=true;}
 postMessage(message){this.message=message;queueMicrotask(()=>{if(!this.closed)this.onmessage({data:C.analyze(message)});});}
}
const context={window:{},document:{getElementById:get,createElement:node,hidden:false},SurfaceCore:C,L,Worker,Intl,Date,Map,Math,Set,Number,String,Uint8ClampedArray,
 setTimeout(fn,ms){if(ms<=150)queueMicrotask(fn);return 1;},clearTimeout(){},fetch:async url=>{reads.push(url);return {ok:true,json:async()=>url==="/api/surface"?manifest:snapshot};}};
vm.runInNewContext(fs.readFileSync("static/surface-views.js","utf8"),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 assert.equal(reads.length,0,"Surface does not fetch at METAR startup");
 get("surface").hidden=false;context.window.WeatherSurfaceViews.select("surface");await flush();
 assert.ok(get("surface-status").textContent.includes("9 usable sites"),get("surface-status").textContent);assert.equal(groups[0].items.length,9);
 assert.equal(reads.length,2);assert.ok(groups[0].items.every(m=>m.value.options.icon.html.includes("metar-plot")));
 get("surface-field").value="windMph";get("surface-field").events.change();await flush();
 assert.ok(get("surface-status").textContent.includes("support this field"));assert.ok(groups[2].items.length>0,"Analyzed wind flow arrows are drawn");
 assert.ok(get("surface-legend").children.length>0);
 get("surface-source").value="mndot";get("surface-source").events.change();await flush();
 assert.ok(get("surface-status").textContent.includes("2 usable sites"));
 get("surface-quality").value="verified";get("surface-quality").events.change();await flush();
 assert.ok(get("surface-status").textContent.includes("1 usable sites"));
 get("surface-timeline").events.input({target:{value:"0"}});await flush();
 assert.ok(get("surface-status").textContent.includes("No saved observations"));assert.equal(groups[0].items.length,0);
 get("surface-timeline").events.input({target:{value:"11"}});await flush();assert.equal(reads.length,2,"Saved hourly payload is reused");
 get("surface-list").open=true;get("surface-list").events.toggle();assert.equal(get("surface-rows").children.length,1);
 context.window.WeatherSurfaceViews.select("metar-clouds");assert.ok(jobs.at(-1).closed,"Leaving cancels analysis");
 console.log("Surface viewer checks passed: lazy reads, controls, field rendering, wind vectors, source/QC comparisons, sparse hours, cache reuse and worker cancellation.");
})().catch(error=>{console.error(error);process.exitCode=1;});
