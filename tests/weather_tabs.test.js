"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),selected=[],windowEvents={};let sourceFetches=0;const cloudSelections=[],airSelections=[],hrmetarSelections=[];
function node(){return{hidden:false,tabIndex:0,events:{},textContent:'',writes:[],classList:{contains(){return false;},add(){},remove(){}},setAttribute(k,v){this[k]=v;this.writes.push([k,v]);},getAttribute(k){return this[k]||null;},addEventListener(k,f){this.events[k]=f;},focus(){this.focused=true;}};}
function get(id){assert.ok(!['current','tab-current','metar-clouds','tab-metar-clouds','mesonet','tab-mesonet','metar','tab-metar'].includes(id),'Removed UI accessed');if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}
const context={document:{getElementById:get,addEventListener(){},hidden:false,body:{classList:{toggle(){}}}},Intl,Date,Math,Map,Set,window:{addEventListener(name,callback){windowEvents[name]=callback;},WeatherAirQuality:{select(id){airSelections.push(id);}},WeatherCloudHeights:{select(id){cloudSelections.push(id);}},WeatherFullscreen:{attach(){}},WeatherHrmetar:{select(id){hrmetarSelections.push(id);}},WeatherObservations:{select(id){if(id==="observations")selected.push("observations");}},WeatherMetars:{select(id){if(id==="clouds")selected.push("clouds");}},WeatherPrepared:{subscribe(){},prime(){}}},WeatherCloudViews:{select(id){selected.push(id);}},fetch(){sourceFetches++;throw Error('Unexpected startup fetch');},setTimeout(){},setInterval(){},clearTimeout(){}};
vm.runInNewContext(fs.readFileSync('static/app.js','utf8'),context);
assert.equal(selected[0],'observations');assert.equal(get('observations').hidden,false);
for(const id of ['clouds','radar','satellite','forecast','hourly','hrmetar','air-quality'])assert.equal(get(id).hidden,true);
get('tab-observations').events.keydown({key:'ArrowRight',preventDefault(){}});
assert.equal(get('clouds').hidden,false);assert.equal(get('observations').hidden,true);
assert.equal(selected.at(-1),'clouds');assert.equal(get('tab-clouds').focused,true);
assert.equal(sourceFetches,0);
get('tab-hrmetar').events.click();assert.equal(get('hrmetar').hidden,false);
assert.equal(get('hourly').hidden,true);assert.equal(hrmetarSelections.at(-1),'hrmetar');
get('tab-air-quality').events.click();assert.equal(get('air-quality').hidden,false);
windowEvents.pageshow({persisted:true});
assert.equal(get('observations').hidden,false);
assert.equal(get('air-quality').hidden,true);
get('tab-air-quality').events.click();assert.equal(get('air-quality').hidden,false);assert.equal(airSelections.at(-1),'air-quality');
assert.equal(sourceFetches,0);
get('tab-satellite').events.keydown({key:'Home',preventDefault(){}});
assert.equal(selected.at(-1),'observations');assert.equal(get('tab-observations').focused,true);
console.log('Weather tab checks passed: OBSERVATIONS first on load and restore, with keyboard navigation.');
