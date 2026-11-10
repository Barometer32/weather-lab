"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const nodes=new Map(),handlers={};
function element(){return{children:[],append(node){this.children.push(node);},
  replaceChildren(...nodes){this.children=nodes;},addEventListener(){}};}
const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
const context={document:{getElementById:get,createElement:element},Intl,Date,Number,Math,setInterval(){},
  window:{WeatherPrepared:{subscribe(url,fn){handlers[url]=fn;}}}};
vm.runInNewContext(fs.readFileSync("static/hourly-observation-views.js","utf8"),context);
const reading={hour:"2026-11-09T18:00:00Z",count:3,tempF:58.2,dewpointF:39,wind:{direction:315,speedMph:10}};
const adopt=handlers["/api/observations/hourly"];
const pending={hour:"2026-11-09T19:00:00Z",count:2};
adopt({current:reading,history:[pending,reading],stationCount:3});
assert.equal(get("observations-temperature").textContent,"58.2°F");
assert.equal(get("observations-dewpoint").textContent,"39.0°F");
assert.equal(get("observations-wind").textContent,"NW 10 mph");
assert.match(get("hourly-observation-time").textContent,/12:00 PM CST.*New hour pending/);
const rows=get("hourly-observation-history").children;
assert.equal(rows.length,2);
assert.equal(rows[0].children[1].textContent,"—");
assert.equal(rows[0].children[4].textContent,"2/3");
assert.equal(rows[1].children[1].textContent,"58.2°F");
