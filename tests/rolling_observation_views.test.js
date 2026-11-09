"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const now=Date.parse("2026-11-09T18:05:00Z"),utc=ms=>new Date(ms).toISOString();
class Clock extends Date {static now(){return now;}}
const nodes=new Map(),handlers={};
function element(){return{children:[],append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},addEventListener(){}};}
const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
const context={document:{getElementById:get,createElement:element},Intl,Date:Clock,Number,Math,setInterval(){},
 window:{WeatherPrepared:{subscribe(url,fn){handlers[url]=fn;}},WeatherSun:{elevation(){return 22.2;}}}};
vm.runInNewContext(fs.readFileSync("static/rolling-observation-views.js","utf8"),context);
const reading={observedAt:utc(now-600000),tempF:58,dewpointF:39,wind:{direction:315,speedMph:10}};
const adopt=handlers["/api/observations/rolling"];
adopt({current:reading,lastCompleteAt:reading.observedAt,history:[{time:utc(now-300000),reading}]});
assert.equal(get("observations-temperature").textContent,"58°F");
assert.equal(get("observations-dewpoint").textContent,"39°F");
assert.equal(get("observations-wind").textContent,"NW 10 mph");
const heading=get("rolling-observation-history").children[0].children[0];
assert.match(heading.textContent,/12:00 PM CST/);
assert.equal(heading.children.length,0);
assert.match(get("rolling-observation-time").textContent,/11:55 AM CST/);
adopt({current:{...reading,observedAt:utc(now-31*60000)},lastCompleteAt:utc(now-31*60000),history:[]});
assert.equal(get("observations-temperature").textContent,"—");
assert.match(get("rolling-observation-time").textContent,/No matched observation/);
