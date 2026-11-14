"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),model=require("../static/conditions-model.js");
const nodes=new Map(),events={},windowEvents={};let geoAccess=0,watchCalls=0,clearCalls=0,fixCallback,subscriber;
const node=()=>({textContent:"",value:"",hidden:false,disabled:false,events:{},selectedOptions:[{textContent:"Hopkins"}],children:[],addEventListener(k,f){this.events[k]=f;},append(v){this.children.push(v);},replaceChildren(){this.children=[];}});
function get(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}
get("conditions-scope").value="nearby";
const navigator={};Object.defineProperty(navigator,"geolocation",{get(){geoAccess++;return {watchPosition(callback){watchCalls++;fixCallback=callback;return 7;},clearWatch(id){assert.equal(id,7);clearCalls++;}};}});
const date=new Date(),stamp=new Date(date-300000).toISOString();
const data={checkedAt:date.toISOString(),serverTime:date.toISOString(),stations:[44.96,44.98,45].map((lat,i)=>({station:"REF"+i,lat,lon:-93.414,time:stamp,tempF:40,dewpointF:25,kind:"reference",wind:{speedMph:5,direction:0}}))};
const document={hidden:false,getElementById:get,createElement:node,addEventListener(k,f){events[k]=f;}};
const window={WeatherConditionsModel:model,WeatherSun:{elevation(){return 20;}},WeatherPrepared:{subscribe(url,callback){subscriber=callback;},async read(){return data;}},addEventListener(k,f){windowEvents[k]=f;}};
vm.runInNewContext(fs.readFileSync("static/conditions-views.js","utf8"),{window,document,navigator,Date,Intl,Math,Number,Map,Set,setInterval(){}});
(async()=>{
  assert.equal(geoAccess,0,"Loading the website must not access GPS");
  window.WeatherConditions.select("conditions");await new Promise(resolve=>setImmediate(resolve));
  assert.equal(geoAccess,0,"Opening CONDITIONS must not prompt for location");
  assert.equal(get("conditions-temp").textContent,"40°F");
  get("conditions-locate").events.click();assert.equal(watchCalls,1);
  fixCallback({coords:{latitude:44.95,longitude:-93.414,accuracy:12}});
  assert.match(get("conditions-location").textContent,/device/);
  document.hidden=true;events.visibilitychange();assert.equal(clearCalls,1);
  window.WeatherConditions.select("metar");document.hidden=false;events.visibilitychange();assert.equal(watchCalls,1,"GPS stays paused on other tabs");
  window.WeatherConditions.select("conditions");assert.equal(watchCalls,2);
  get("conditions-stop").events.click();assert.equal(clearCalls,2);
  subscriber({...data,_savedCopy:true,serverTime:new Date(date-3600000).toISOString(),checkedAt:new Date(date-720000).toISOString()});
  assert.equal(get("conditions-temp").textContent,"—","An old cached server time must not rewind measurement ages");
  assert.match(get("conditions-status").textContent,/withheld/i);
  console.log("Conditions UI checks passed: explicit location permission, pause/resume, local-only coordinates and stale cache handling.");
})().catch(error=>{console.error(error);process.exitCode=1;});
