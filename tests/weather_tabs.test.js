"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),selected=[];let sourceFetches=0;
let clock=Date.UTC(2026,9,16,14,17),timers=[];
class ClockDate extends Date{static now(){return clock;}}
function node(){return{hidden:false,tabIndex:0,events:{},textContent:'',classList:{contains(){return false;},add(){},remove(){}},setAttribute(k,v){this[k]=v;},addEventListener(k,f){this.events[k]=f;},focus(){this.focused=true;}};}
function get(id){assert.ok(!id.includes('observations'),'Retired observation element was accessed');if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}
const context={document:{getElementById:get,addEventListener(){},hidden:false,body:{classList:{toggle(){}}}},Intl,Date:ClockDate,Math,Map,Set,window:{},WeatherCloudViews:{select(id){selected.push(id);}},fetch(){sourceFetches++;throw Error('No non-METAR startup fetch');},setTimeout(callback,delay){timers.push({callback,delay});},setInterval(){},clearTimeout(){}};
vm.runInNewContext(fs.readFileSync('static/app.js','utf8'),context);
assert.equal(selected[0],'metar-clouds');assert.equal(get('metar-clouds').hidden,false);
for(const id of ['radar','satellite','forecast'])assert.equal(get(id).hidden,true);
assert.equal(sourceFetches,0);
const forecastTimer=timers.find(t=>t.delay===810000); // 14:17 -> 14:30:30.
assert.ok(forecastTimer);
clock=Date.UTC(2026,9,16,14,30,30);forecastTimer.callback();
assert.equal(timers.at(-1).delay,1800000); // Next read: 15:00:30.
assert.equal(sourceFetches,0); // Hidden forecast does not fetch.
get('tab-metar-clouds').events.keydown({key:'Home',preventDefault(){}});
assert.equal(selected.at(-1),'metar-clouds');assert.equal(get('tab-metar-clouds').focused,true);
console.log('Weather tab checks passed: METAR first/default, no observation access or polling, preserved keyboard navigation.');
