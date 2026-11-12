'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function classes(){const values=new Set();return{add(v){values.add(v);},remove(v){values.delete(v);},contains(v){return values.has(v);}};}
const nodes=new Map(),events={},windowEvents={},viewportEvents={},resizes={radar:0,metar:0,satellite:0};
const get=id=>{if(!nodes.has(id))nodes.set(id,{id,classList:classes(),events:{},setAttribute(k,v){this[k]=v;},addEventListener(k,f){this.events[k]=f;},focus(){this.focused=true;}});return nodes.get(id);};
const root={},document={documentElement:root,getElementById:get,fullscreenElement:null,body:{classList:classes()},addEventListener(k,f){events[k]=f;},async exitFullscreen(){this.fullscreenElement=null;events.fullscreenchange();}};
const context={document,window:{requestAnimationFrame(f){f();},addEventListener(k,f){windowEvents[k]=f;},visualViewport:{addEventListener(k,f){viewportEvents[k]=f;}}}};
vm.runInNewContext(fs.readFileSync('static/map-fullscreen.js','utf8'),context);
for(const id of ['radar','metar','satellite'])context.window.WeatherFullscreen.attach({surfaceId:id,buttonId:id+'-button',label:id,onResize(){resizes[id]++;}});
const click=id=>get(id+'-button').events.click();
(async()=>{
 root.requestFullscreen=async function(options){assert.equal(options.navigationUI,'hide');document.fullscreenElement=this;events.fullscreenchange();};
 await click('radar');assert.equal(document.fullscreenElement,root,'Fullscreen includes navigation, not just one map');assert.ok(document.body.classList.contains('map-focus'));
 context.window.WeatherFullscreen.select('metar');assert.equal(get('metar-button').textContent,'Close','Switching maps preserves expanded mode');assert.equal(document.fullscreenElement,root);
 await click('metar');assert.equal(document.fullscreenElement,null);assert.ok(!document.body.classList.contains('map-focus'));
 delete root.requestFullscreen;
 await click('satellite');assert.ok(document.body.classList.contains('map-focus'),'iPhone fallback fills the app viewport');assert.ok(!get('satellite').classList.contains('expanded'),'No fixed overlay covers the page tabs');
 let before=resizes.satellite;windowEvents.resize();viewportEvents.resize();assert.equal(resizes.satellite,before+2);
 context.window.WeatherFullscreen.select('forecast');assert.ok(!document.body.classList.contains('map-focus'),'Forecast gets its normal heading and scrollable list');
 await click('metar');let escaped=false;events.keydown({key:'Escape',preventDefault(){escaped=true;}});assert.ok(escaped);assert.ok(!document.body.classList.contains('map-focus'));
 root.requestFullscreen=async()=>{throw Error('Unsupported');};await click('radar');assert.ok(document.body.classList.contains('map-focus'));await click('radar');assert.ok(!document.body.classList.contains('map-focus'));
 console.log('Fullscreen checks passed: whole-app native mode, visible page navigation, phone fallback, tab changes, Escape and resize.');
})().catch(error=>{console.error(error);process.exitCode=1;});
