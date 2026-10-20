"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),selected=[];let sourceFetches=0;
function node(){return{hidden:false,tabIndex:0,events:{},textContent:'',classList:{contains(){return false;},add(){},remove(){}},setAttribute(k,v){this[k]=v;},addEventListener(k,f){this.events[k]=f;},focus(){this.focused=true;}};}
function get(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}
const context={document:{getElementById:get,addEventListener(){},hidden:false,body:{classList:{toggle(){}}}},Intl,Date,Math,Map,Set,window:{WeatherCurrentViews:{select(id){selected.push("current:"+id);}}},WeatherCloudViews:{select(id){selected.push(id);}},fetch(){sourceFetches++;throw Error('No non-METAR startup fetch');},setTimeout(){},setInterval(){},clearTimeout(){}};
vm.runInNewContext(fs.readFileSync('static/app.js','utf8'),context);
assert.equal(selected[0],'current');assert.equal(selected[1],'current:current');assert.equal(get('current').hidden,false);
for(const id of ['metar-clouds','radar','satellite','forecast'])assert.equal(get(id).hidden,true);
assert.equal(sourceFetches,0);
get('tab-metar-clouds').events.keydown({key:'Home',preventDefault(){}});
assert.equal(selected.at(-1),'current:current');assert.equal(get('tab-current').focused,true);
console.log('Weather tab checks passed: Current first/default, independent tab handlers, preserved keyboard navigation.');

