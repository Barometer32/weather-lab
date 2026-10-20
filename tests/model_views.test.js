"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
class Node {
  constructor(){this.children=[];this.events={};this.hidden=false;this.textContent="";}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];}
  addEventListener(name,fn){this.events[name]=fn;}
}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
const cycle=new Date("2026-10-20T12:00:00Z");
const data={available:true,cycleTime:cycle.toISOString(),status:{state:"ready"},hours:Array.from({length:16},(_,i)=>{
 const validTime=new Date(+cycle+(i+2)*3600000).toISOString();
 return {forecastHour:i+2,validTime,precipEnd:validTime,precipStart:new Date(+cycle+(i+1)*3600000).toISOString(),tempF:51.4,dewpointF:45.1,wind:{speedKt:10.6,direction:359.8},precipIn:i===0?.1:i===1?.002:0,cloudPct:75,cloudCategory:"BK",ceilingFtAGL:2700};
})};
let requests=0,payload={available:false,status:{state:"collecting",completed:7,total:32}},failed=false;
const document={getElementById:get,createElement(){return new Node();},addEventListener(){},hidden:false};
const context={document,window:{},Intl,Date,Number,String,Math,setInterval(){},fetch:async(url)=>{requests++;assert.equal(url,"/api/models");return{ok:!failed,json:async()=>payload};}};
get("models-table").hidden=true;
vm.runInNewContext(fs.readFileSync("static/model-views.js","utf8"),context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 assert.equal(requests,0);
 context.window.WeatherModelViews.select("radar");assert.equal(requests,0);
 context.window.WeatherModelViews.select("models");await tick();
 assert.match(get("models-status").textContent,/7 \/ 32/);assert.equal(get("models-table").hidden,true);
 payload=data;get("refresh-models").events.click();await tick();
 assert.equal(get("models-hours").children.length,17);
 assert.equal(get("models-rows").children.length,7);
 assert.equal(get("models-rows").children[4].children[1].textContent,"0.10");
 assert.equal(get("models-rows").children[4].children[2].textContent,"<.01");
 assert.equal(get("models-rows").children[4].children[3].textContent,"0.00");
 assert.match(get("models-rows").children[4].children[1].title,/hour ending/);
 assert.equal(get("models-rows").children[2].children[1].textContent,"000");
 assert.equal(get("models-rows").children[6].children[1].textContent,"27");
 assert.equal(get("models-table").hidden,false);
 const oldRows=get("models-rows").children;
 failed=true;payload={error:"Temporarily unavailable"};get("refresh-models").events.click();await tick();
 assert.equal(get("models-rows").children,oldRows);
 assert.match(get("models-status").textContent,/previous successful refresh/);
 assert.equal(get("refresh-models").disabled,false);
 console.log("Model table checks passed: saved-only loading, F02–17, hourly precipitation, progress and retained table on error.");
})().catch(error=>{console.error(error);process.exitCode=1;});
