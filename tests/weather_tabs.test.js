"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),selected=[];let sourceFetches=0;const cloudSelections=[],airSelections=[];
function node(){return{hidden:false,tabIndex:0,events:{},textContent:'',writes:[],classList:{contains(){return false;},add(){},remove(){}},setAttribute(k,v){this[k]=v;this.writes.push([k,v]);},getAttribute(k){return this[k]||null;},addEventListener(k,f){this.events[k]=f;},focus(){this.focused=true;}};}
function get(id){assert.ok(id!=='current'&&id!=='tab-current','Removed Current UI accessed');if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}
const context={document:{getElementById:get,addEventListener(){},hidden:false,body:{classList:{toggle(){}}}},Intl,Date,Math,Map,Set,window:{WeatherAirQuality:{select(id){airSelections.push(id);}},WeatherCloudHeights:{select(id){cloudSelections.push(id);}},WeatherFullscreen:{attach(){}},WeatherCloudViews:{select(id){selected.push("metar:"+id);}}},WeatherCloudViews:{select(id){selected.push(id);}},fetch(){sourceFetches++;throw Error('No non-METAR startup fetch');},setTimeout(){},setInterval(){},clearTimeout(){}};
vm.runInNewContext(fs.readFileSync('static/app.js','utf8'),context);
assert.equal(selected[0],'metar:metar-clouds');assert.equal(get('metar-clouds').hidden,false);
for(const id of ['radar','clouds','satellite','forecast','air-quality'])assert.equal(get(id).hidden,true);
assert.equal(sourceFetches,0);
get('tab-clouds').events.click();assert.equal(get('clouds').hidden,false);assert.equal(get('metar-clouds').hidden,true);assert.equal(cloudSelections.at(-1),'clouds');
get('tab-air-quality').events.click();assert.equal(get('air-quality').hidden,false);assert.equal(airSelections.at(-1),'air-quality');
assert.equal(sourceFetches,0);
get('tab-satellite').events.keydown({key:'Home',preventDefault(){}});
assert.equal(selected.at(-1),'metar:metar-clouds');assert.equal(get('tab-metar-clouds').focused,true);
console.log('Weather tab checks passed: METAR first/default, independent tab handlers, preserved keyboard navigation.');

