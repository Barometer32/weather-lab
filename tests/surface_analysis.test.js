"use strict";
const assert=require("node:assert/strict"),C=require("../static/surface-core.js");
function station(lat,lon,t=70,dir=0,speed=10,descriptor="V",kind="mesonet",name="test"){
  return {station:name,id:name,lat,lon,kind,network:kind==="road"?"MN_RWIS":"test",tempF:t,dewpointF:50,rh:60,windMph:speed,direction:dir,
    uMph:-speed*Math.sin(dir*Math.PI/180),vMph:-speed*Math.cos(dir*Math.PI/180),qc:Object.fromEntries(["tempF","dewpointF","rh","windMph","direction","vector"].map(k=>[k,{accepted:true,descriptor}]))};
}
const points=[station(44.95,-93.05),station(44.95,-93.35),station(45.15,-93.05),station(45.15,-93.35)];
assert.equal(C.build(points,"tempF").sample(45.05,-93.2).value,70);
assert.equal(C.build(points.slice(0,2),"tempF").sample(45.05,-93.2),null,"Never invent a field from fewer than three sites");
assert.equal(C.build(points,"tempF").sample(46,-94),null,"No extrapolation outside the station hull");
const wrapped=points.map((p,i)=>({...p,uMph:-10*Math.sin((i%2?10:350)*Math.PI/180),vMph:-10*Math.cos((i%2?10:350)*Math.PI/180)}));
const w=C.build(wrapped,"windMph").sample(45.05,-93.2);
assert.ok(Math.abs(w.u)<.001&&w.v<0,"350/10 degrees combine into northerly flow, not southerly");
assert.ok(Math.abs(w.value-9.848)<.001,"Speed comes from resultant u/v");
const opposed=points.map((p,i)=>({...p,uMph:i%2?10:-10,vMph:0}));
assert.ok(C.build(opposed,"windMph").sample(45.05,-93.2).value<.01,"Opposing winds cancel");
const bad={...points[0],qc:{tempF:{accepted:false,descriptor:"Q"}}};
assert.equal(C.build([bad,...points.slice(1)],"tempF").count,3);
const local=station(45,-93,70,0,10,"LOCAL","road","MN001");
assert.equal(C.filter([local],"all","verified").length,0);
assert.equal(C.filter([local],"mndot","passed").length,1);
assert.equal(C.filter([local],"airports","passed").length,0);
assert.equal(C.filter([station(45,-93,70,0,10,"V","airport","KCFE")]).length,0);
assert.deepEqual(C.color(70,"tempF"),C.color(70,"dewpointF"),"Equal Fahrenheit values have equal colors");
assert.deepEqual(C.color(70,"tempF","colorblind"),C.color(70,"dewpointF","colorblind"));
assert.deepEqual(C.color(10,"windMph"),C.color(10,"gustMph"));
const duplicate={...points[0],id:"alias"};assert.equal(C.build([...points,duplicate],"tempF").count,4);
const front=points.map((p,i)=>({...p,tempF:i%2?80:60}));
const near=C.build(front,"tempF").sample(45.0,-93.34).value;assert.ok(near>75,"Local gradients survive instead of collapsing into a metro average");
const result=C.analyze({id:7,stations:front,bounds:[[44.95,-93.35],[45.15,-93.05]],width:20,height:20,field:"tempF",quality:"passed",detail:"detail"});
assert.equal(result.id,7);assert.ok(result.values.some(Number.isFinite));assert.ok(result.contours.length);
assert.ok(result.values.every(v=>!Number.isFinite(v)||v>=60&&v<=80),"Interpolation never overshoots observations");
console.log("Surface analysis passed: QC, source filters, fixed palettes, sparse masks, deduplication, gradients, contours and vector wind interpolation.");
