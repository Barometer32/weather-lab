"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),selected=[];let sourceFetches=0;
function node(){return{hidden:false,tabIndex:0,events:{},textContent:'',writes:[],classList:{contains(){return false;},add(){},remove(){}},setAttribute(k,v){this[k]=v;this.writes.push([k,v]);},getAttribute(k){return this[k]||null;},addEventListener(k,f){this.events[k]=f;},focus(){this.focused=true;}};}
function get(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}
const context={document:{getElementById:get,addEventListener(){},hidden:false,body:{classList:{toggle(){}}}},Intl,Date,Math,Map,Set,window:{WeatherFullscreen:{attach(){}},WeatherCurrentViews:{select(id){selected.push("current:"+id);}}},WeatherCloudViews:{select(id){selected.push(id);}},fetch(){sourceFetches++;throw Error('No non-METAR startup fetch');},setTimeout(){},setInterval(){},clearTimeout(){}};
vm.runInNewContext(fs.readFileSync('static/app.js','utf8'),context);
assert.equal(selected[0],'current');assert.equal(selected[1],'current:current');assert.equal(get('current').hidden,false);
for(const id of ['metar-clouds','radar','satellite','forecast','air-quality'])assert.equal(get(id).hidden,true);
assert.equal(sourceFetches,0);
const frame=get('air-quality-map'),url='https://gis-ext-aqi.pca.mn.gov/aqi/aqi-current-conditions.html';
frame.setAttribute('data-src',url);
assert.equal(frame.getAttribute('src'),null);
get('tab-air-quality').events.click();
assert.equal(get('air-quality').hidden,false);
assert.equal(frame.getAttribute('src'),url);
get('tab-current').events.click();get('tab-air-quality').events.click();
assert.equal(frame.writes.filter(([key])=>key==='src').length,1);
get('refresh-air-quality').events.click();
assert.equal(frame.writes.filter(([key])=>key==='src').length,2);
assert.equal(sourceFetches,0);
get('tab-metar-clouds').events.keydown({key:'Home',preventDefault(){}});
assert.equal(selected.at(-1),'current:current');assert.equal(get('tab-current').focused,true);
console.log('Weather tab checks passed: Current first/default, independent tab handlers, preserved keyboard navigation.');

