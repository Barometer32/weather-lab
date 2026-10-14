'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();
function element(){return {value:'',checked:true,textContent:'',children:[],events:{},style:{},setAttribute(key,value){this[key]=value;},append(...v){this.children.push(...v);},replaceChildren(){this.children=[];},addEventListener(k,f){this.events[k]=f;}};}
function get(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}
get('surface-field').value='tempF';
const pending=new Map(),shown=[];let fetches=0,clears=0;
const layer=()=>({on(){return this;},addTo(){return this;},bindTooltip(){return this;}});
const panes=new Map();
const context={document:{getElementById:get,createElement:element},Intl,Date,Map,Error,setTimeout(){},window:{},
 fetch(url){fetches++;return new Promise(resolve=>pending.set(url,result=>resolve({ok:true,json:async()=>result})));},
 L:{map(){return {fitBounds(){},createPane(name){const pane={style:{}};panes.set(name,pane);return pane;},getPane(name){return panes.get(name);},invalidateSize(){}};},tileLayer:layer,
 layerGroup(){return {addTo(){return this;},clearLayers(){clears++;shown.length=0;}};},imageOverlay(url){shown.push({kind:'image',url});return layer();},geoJSON:layer,divIcon(options){return options;},marker(coords,options){shown.push({kind:'arrow',...options});return layer();},circleMarker(coords,options){const result=layer();result.bindPopup=p=>{shown.push({kind:'point',options,popup:p});return result;};return result;}}};
vm.runInNewContext(fs.readFileSync('static/surface-analysis.js','utf8'),context);
const viewer=context.window.WeatherSurfaceViews;
const station={station:'MN001',stationKey:'MN_RWIS:MN001',name:'Road station',network:'MN_RWIS',lat:45,lon:-93,time:'2026-10-14T20:40:00Z',tempF:110,dewpointF:40,wind:{speedMph:10,direction:359},analysisQc:{tempF:{status:'suspect',reason:'Nearby disagreement'},dewpointF:{status:'screened',reason:'Consistent'},wind:{status:'screened',reason:'Consistent'}}};
function product(){return {imageUrl:'/image.png',palette:[[0,'#fff'],[10,'#080'],[50,'#f00']],contours:{type:'FeatureCollection',features:[]},qc:{suspect:1},used:20,supportedCells:10};}
function manifest(hour){return {hour,bounds:[[40,-100],[50,-85]],fields:{tempF:{...product(),paletteMode:'discrete',interval:5,palette:[[40,'#0f0'],[45,'#cf0'],[50,'#ff0'],[55,'#fc0']]},dewpointF:product(),wind:{...product(),arrows:[{lat:45,lon:-93,speed:10,direction:359}]}}};}
const dataset={coverage:[{network:'MN_RWIS',available:169}]};
const old={hour:'2026-10-14T20:00:00Z',analysisUrl:'/old.json',stations:[station]};
const current={hour:'2026-10-14T21:00:00Z',analysisUrl:'/new.json',stations:[station]};
(async()=>{
 const first=viewer.setFrame(old,dataset),second=viewer.setFrame(current,dataset);
 pending.get('/new.json')(manifest(current.hour));await second;
 assert.match(get('surface-status').textContent,/4:00 PM/);
 assert.equal(shown.find(s=>s.kind==='point').options.fillColor,'#69706f');
 assert.match(get('surface-legend').children[0].textContent,/5°F bands/);
 assert.match(get('surface-legend').children[1].style.background,/#0f0 0%,#0f0 33\.333/);
 assert.equal(get('surface-legend').children[1]['aria-label'],'Temperature color scale, 5-degree Fahrenheit bands');
 pending.get('/old.json')(manifest(old.hour));await first;
 assert.match(get('surface-status').textContent,/4:00 PM/); // A slow old response cannot replace the new hour.
 const before=clears;await viewer.setFrame(current,dataset);assert.equal(clears,before);assert.equal(fetches,2);
 get('surface-field').value='wind';get('surface-field').events.change();
 assert.ok(shown.find(s=>s.kind==='arrow').icon.html.includes('rotate(179)'));
 get('surface-points').checked=false;get('surface-points').events.change();assert.ok(!shown.some(s=>s.kind==='point'));
 const gap={hour:'2026-10-14T19:00:00Z',stations:[]};await viewer.setFrame(gap,dataset);
 assert.match(get('surface-status').textContent,/No prepared contours/);assert.equal(shown.length,0);
 await viewer.setFrame(old,dataset);assert.equal(fetches,2); // History uses the prepared cache.
 assert.match(get('surface-status').textContent,/3:00 PM/);
 console.log('Surface-view checks passed: selected-hour maps, excluded point styling, wind vectors, race protection, prepared cache and explicit history gaps.');
})().catch(error=>{console.error(error);process.exitCode=1;});
