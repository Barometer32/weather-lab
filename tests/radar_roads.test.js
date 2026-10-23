"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
let layer,panes={};
const context={window:{},URLSearchParams,L:{TileLayer:{extend(methods){
  return class {
    constructor(url,options){this.options=options;Object.assign(this,methods);layer=this;}
    on(event,callback){this[event]=callback;return this;}
    addTo(map){this.map=map;return this;}
  };
}}}};
vm.runInNewContext(fs.readFileSync("static/radar-roads.js","utf8"),context);
const map={createPane(name){panes[name]={style:{}};},getPane(name){return panes[name];}};
let failed=false;
context.window.WeatherRadarRoads.addTo(map,()=>{failed=true;});
assert.equal(layer.map,map);
assert.equal(panes.roads.style.pointerEvents,"none");
assert.ok(panes.roads.style.zIndex>350&&panes.roads.style.zIndex<410,"roads stay above echoes and below boundaries");
assert.ok(layer.options.opacity>0&&layer.options.opacity<=.3,"roads remain faint");
const url=new URL(layer.getTileUrl({x:123,y:184,z:9})),params=url.searchParams;
assert.equal(url.hostname,"tigerweb.geo.census.gov");
assert.equal(params.get("transparent"),"true");assert.equal(params.get("format"),"png32");
assert.equal(params.get("imageSR"),"3857");assert.equal(params.get("size"),"256,256");
const layers=JSON.parse(params.get("dynamicLayers"));
assert.deepEqual(layers.map(l=>l.source.mapLayerId),[1,3],"only primary and secondary roads; no railroads or local street grid");
for(const l of layers){
 assert.equal(l.drawingInfo.showLabels,false);assert.deepEqual(l.drawingInfo.labelingInfo,[]);
 assert.ok(l.drawingInfo.renderer.symbol.width<=.8);

}
for(let z=5;z<=13;z++){
 const q=new URL(layer.getTileUrl({x:1,y:1,z})).searchParams;
 const ids=JSON.parse(q.get("dynamicLayers")).map(l=>l.source.mapLayerId);
 assert.deepEqual(ids,z===5||z===7?[0]:z===6||z===8||z===9?[1,3]:z===10?[2,4]:z<13?[2,5]:[2,6],"use the published road layer at each export scale");
}
const box=params.get("bbox").split(",").map(Number),next=new URL(layer.getTileUrl({x:124,y:184,z:9})).searchParams.get("bbox").split(",").map(Number);
assert.ok(Math.abs(box[2]-next[0])<1e-7,"neighboring tiles line up without geographic shifts");
const west=box[0]/20037508.342789244*180;
assert.ok(west>-94&&west<-93,"metro tile is projected in Minnesota");
layer.tileerror();assert.ok(failed,"road failures have a separate nonblocking notice");
if(process.env.ROAD_TEST_URL)fs.writeFileSync(process.env.ROAD_TEST_URL,url.href);
console.log("Radar road checks passed: label-free major roads, faint styling, aligned tiles and independent failure notice.");
