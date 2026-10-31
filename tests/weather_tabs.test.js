"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),selected=[];let sourceFetches=0;const cloudSelections=[],airSelections=[];
function node(){return{hidden:false,tabIndex:0,events:{},textContent:'',writes:[],classList:{contains(){return false;},add(){},remove(){}},setAttribute(k,v){this[k]=v;this.writes.push([k,v]);},getAttribute(k){return this[k]||null;},addEventListener(k,f){this.events[k]=f;},focus(){this.focused=true;}};}
function get(id){assert.ok(!['current','tab-current','metar-clouds','tab-metar-clouds','observations','tab-observations','clouds','tab-clouds'].includes(id),'Removed UI accessed');if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}
const context={document:{getElementById:get,addEventListener(){},hidden:false,body:{classList:{toggle(){}}}},Intl,Date,Math,Map,Set,window:{addEventListener(){},WeatherAirQuality:{select(id){airSelections.push(id);}},WeatherCloudHeights:{select(id){cloudSelections.push(id);}},WeatherFullscreen:{attach(){}},WeatherMetars:{select(id){selected.push("metar:"+id);}},WeatherPrepared:{subscribe(){},prime(){}}},WeatherCloudViews:{select(id){selected.push(id);}},fetch(){sourceFetches++;throw Error('No non-METAR startup fetch');},setTimeout(){},setInterval(){},clearTimeout(){}};
vm.runInNewContext(fs.readFileSync('static/app.js','utf8'),context);
assert.equal(selected[0],'metar:metar');assert.equal(get('metar').hidden,false);
for(const id of ['radar','satellite','forecast','air-quality'])assert.equal(get(id).hidden,true);
assert.equal(sourceFetches,0);
get('tab-air-quality').events.click();assert.equal(get('air-quality').hidden,false);assert.equal(airSelections.at(-1),'air-quality');
assert.equal(sourceFetches,0);
get('tab-satellite').events.keydown({key:'Home',preventDefault(){}});
assert.equal(selected.at(-1),'metar:metar');assert.equal(get('tab-metar').focused,true);
console.log('Weather tab checks passed: METAR first/default with four products, independent tab handlers, preserved keyboard navigation.');
