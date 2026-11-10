"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const nodes=new Map(),handlers={};
function element(){return{children:[],append(node){this.children.push(node);},
  replaceChildren(...nodes){this.children=nodes;},addEventListener(){}};}
const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
const context={document:{getElementById:get,createElement:element},Intl,Date,Number,Math,setInterval(){},
  window:{WeatherPrepared:{subscribe(url,fn){handlers[url]=fn;}}}};
vm.runInNewContext(fs.readFileSync("static/hourly-observation-views.js","utf8"),context);
const reading={hour:"2026-11-09T18:00:00Z",count:3,complete:true,tempF:58.2,dewpointF:39,wind:{direction:315,speedMph:10.6}};
const adopt=handlers["/api/observations/hourly"];
const pending={hour:"2026-11-09T19:00:00Z",count:2,complete:false};
adopt({current:reading,history:[pending,reading],stationCount:3});
assert.equal(get("observations-temperature").textContent,"58°F");
assert.equal(get("observations-dewpoint").textContent,"39°F");
assert.equal(get("observations-wind").textContent,"NW 11 mph");
assert.match(get("hourly-observation-time").textContent,/12:00 PM CST.*New hour pending/);
const rows=get("hourly-observation-history").children;
assert.equal(rows.length,1);
assert.equal(rows[0].children.length,4);
assert.equal(rows[0].children[1].textContent,"58°F");
assert.doesNotMatch(get("hourly-observation-time").textContent,/3\/3/);
