"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const ids=new Map();
function node(){
  return {children:[],events:{},append(child){this.children.push(child);},
    replaceChildren(){this.children=[];},addEventListener(name,callback){this.events[name]=callback;}};
}
function get(id){
  if(!ids.has(id))ids.set(id,node());
  return ids.get(id);
}
let fail=false,endpoint;
const data={checkedAt:"2026-11-28T04:02:00Z",history:[
  {hour:"2026-11-28T04:00:00Z",tempF:37,dewpointF:28,wind:{speedMph:3,direction:180}},
  {hour:"2026-11-28T02:00:00Z",tempF:40,dewpointF:30,wind:{speedMph:12,direction:225}},
]};
const window={WeatherPrepared:{async read(url){endpoint=url;if(fail)throw Error("Offline");return data;},subscribe(){}}};
vm.runInNewContext(fs.readFileSync("static/observations.js","utf8"),{
  window,document:{getElementById:get,createElement:node},setInterval(){},
});
(async()=>{
  window.WeatherObservations.select("clouds");
  assert.equal(endpoint,undefined);
  window.WeatherObservations.select("observations");
  await new Promise(setImmediate);
  assert.equal(endpoint,"/api/observations");
  assert.equal(get("observations-temperature").textContent,"37°F");
  assert.equal(get("observations-dewpoint").textContent,"28°F");
  assert.equal(get("observations-wind").textContent,"CALM");
  assert.match(get("observations-time").textContent,/^10\s+PM\s+CST$/);
  const rows=get("observations-history").children;
  assert.equal(rows.length,2);
  assert.equal(rows[1].children[3].textContent,"SW 12");
  fail=true;
  await get("refresh-observations").events.click();
  assert.equal(get("observations-history").children,rows);
  console.log("Observations render the latest three-airport average and retain the hourly table on refresh failure.");
})().catch(error=>{console.error(error);process.exitCode=1;});
