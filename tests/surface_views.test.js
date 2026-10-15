'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();
function element(){return {value:'',hidden:false,disabled:false,textContent:'',children:[],events:{},style:{setProperty(){}},setAttribute(key,value){this[key]=value;},append(...v){this.children.push(...v);},replaceChildren(){this.children=[];},addEventListener(k,f){this.events[k]=f;}};}
function get(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}
get('surface-field').value='tempF';
const pending=new Map(),shown=[],timers=[],events={};let fetches=0,clears=0;
const layer=()=>({on(){return this;},addTo(){return this;},bindTooltip(){return this;}});
const panes=new Map();
const context={document:{getElementById:get,createElement:element,hidden:false,addEventListener(k,f){events[k]=f;}},Intl,Date,Map,Set,Error,
 setTimeout(callback,delay){timers.push({callback,delay,cleared:false});return timers.length-1;},clearTimeout(id){if(timers[id])timers[id].cleared=true;},window:{},
 fetch(url){fetches++;return new Promise(resolve=>pending.set(url,result=>resolve({ok:true,json:async()=>result})));},
 L:{map(){return {fitBounds(){},createPane(name){const pane={style:{}};panes.set(name,pane);return pane;},getPane(name){return panes.get(name);},invalidateSize(){}};},tileLayer:layer,
 layerGroup(){return {addTo(){return this;},clearLayers(){clears++;shown.length=0;}};},imageOverlay(url){shown.push({kind:'image',url});return layer();},geoJSON:layer,divIcon(options){return options;},marker(coords,options){shown.push({kind:'arrow',...options});return layer();},circleMarker(){throw Error('Contour maps must never draw station dots');}}};
vm.runInNewContext(fs.readFileSync('static/surface-analysis.js','utf8'),context);
const viewer=context.window.WeatherSurfaceViews;
const station={station:'MN001',stationKey:'MN_RWIS:MN001',network:'MN_RWIS',lat:45,lon:-93,tempF:50,dewpointF:40,wind:{speedMph:10,direction:359}};
const airport={...station,network:'MN_ASOS'},wisconet={...station,network:'WISCONET'};
function product(){return {imageUrl:'/image.png',palette:[[0,'#fff'],[10,'#080'],[50,'#f00']],contours:{type:'FeatureCollection',features:[]},qc:{suspect:1},used:20,supportedCells:10};}
function manifest(hour){return {hour,bounds:[[40,-100],[50,-85]],fields:{tempF:{...product(),paletteMode:'discrete',interval:5,palette:[[40,'#0f0'],[45,'#cf0'],[50,'#ff0'],[55,'#fc0']]},dewpointF:product(),wind:{...product(),paletteMode:'discrete',interval:5,palette:[[0,'#fff'],[5,'#ccc'],[10,'#080']],arrows:[{lat:45,lon:-93,speed:10,direction:359}]}}};}
const old={hour:'2026-10-14T20:00:00Z',analysisUrl:'/old.json',stations:[station,airport,wisconet],sourceHealth:[{source:'AWC METAR',status:'ok',reports:1}],networkHealth:[{network:'MN_RWIS'},{network:'MN_ASOS'},{network:'WISCONET'}]};
const current={...old,hour:'2026-10-14T21:00:00Z',analysisUrl:'/new.json',sourceHealth:[{source:'AWC METAR',status:'failed',reports:0}],networkHealth:[...old.networkHealth,{network:'MN_DCP'}]};
const hours=Array.from({length:10},(_,i)=>({hour:new Date(Date.UTC(2026,9,14,10+i)).toISOString(),stations:[]})).concat(old,current);
const dataset={hour:current.hour,history:hours,delayedNetworks:['MN_RWIS'],expectedNetworks:['MN_RWIS','MN_ASOS','WISCONET','MN_DCP'],coverage:[{network:'MN_RWIS',available:169}]};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const text=id=>get(id).children.map(n=>n.textContent).join('\n');
function scrub(index){get('surface-timeline').events.input({target:{value:String(index)}});}
function field(name){get('surface-field').value=name;get('surface-field').events.change();}
(async()=>{
 const first=viewer.setData(dataset);
 assert.equal(get('surface-timeline').max,'11');assert.equal(get('surface-timeline').value,'11');
 scrub(10);pending.get('/old.json')(manifest(old.hour));await flush();
 assert.match(get('surface-status').textContent,/3:00 PM/);
 assert.ok(!text('surface-feed-status').includes('Feed download failed'));
 // A slow response for the latest hour cannot replace a manually selected hour.
 pending.get('/new.json')(manifest(current.hour));await first;
 assert.match(get('surface-status').textContent,/3:00 PM/);
 assert.equal(get('surface-coverage').children.find(r=>r.children[0].textContent==='MN_RWIS').children[1].textContent,'—');
 assert.match(get('surface-legend').children[0].textContent,/5°F bands/);
 assert.match(get('surface-legend').children[1].style.background,/#0f0 0%,#0f0 33\.333/);
 assert.equal(get('surface-legend').children[1]['aria-label'],'Temperature color scale, 5-degree Fahrenheit bands');
 const before=clears;await viewer.setData(dataset);assert.equal(clears,before);assert.equal(fetches,2);
 field('wind');await flush();assert.equal(get('surface-timeline').value,'11');
 assert.ok(shown.find(s=>s.kind==='arrow').icon.html.includes('rotate(179)'));
 assert.match(get('surface-legend').children[0].textContent,/5 mph bands/);
 assert.equal(get('surface-legend').children[1]['aria-label'],'Wind color scale, 5-mile-per-hour bands');
 assert.deepEqual(get('surface-legend').children[2].children.map(t=>t.textContent),['0','5','10']);
 assert.match(text('surface-feed-status'),/Networks with zero reports: MN_DCP/);
 assert.match(text('surface-feed-status'),/Feed download failed: AWC METAR/);
 assert.match(text('surface-feed-status'),/ASOS \/ airports: 1 · Mesonet \/ road: 1 · Wisconet: 1/);
 field('tempF');await flush();assert.equal(get('surface-timeline').value,'10');
 assert.equal(get('surface-play')['aria-pressed'],'false');
 // A station-map rerender leaves the contour time untouched.
 await viewer.setData(dataset);assert.equal(get('surface-timeline').value,'10');
 scrub(0);await flush();assert.equal(shown.length,0);assert.match(get('surface-status').textContent,/No prepared contours/);
 assert.ok(!text('surface-feed-status').includes('Feed download failed: AWC'));
 assert.match(text('surface-feed-status'),/not recorded/);
 assert.match(get('surface-time').textContent,/hourly 1\/12/);
 scrub(10);await flush();assert.equal(fetches,2);
 // Refresh preserves historical selections but fields following latest advance.
 const next={...current,hour:'2026-10-14T22:00:00Z',analysisUrl:'/next.json'};
 const updated={...dataset,hour:next.hour,history:hours.slice(1).concat(next)};
 await viewer.setData(updated);assert.equal(get('surface-timeline').value,'9');
 field('wind');pending.get('/next.json')(manifest(next.hour));await flush();
 assert.equal(get('surface-timeline').value,'11');
 // Playback loops over all slots, including empty hours; manual input stops it.
 get('surface-play').events.click();await flush();assert.equal(get('surface-timeline').value,'0');
 assert.equal(get('surface-play')['aria-pressed'],'true');
 timers.findLast(t=>t.delay===1100&&!t.cleared).callback();await flush();
 assert.equal(get('surface-timeline').value,'1');
 scrub(10);await flush();assert.equal(get('surface-play')['aria-pressed'],'false');
 get('surface-play').events.click();await flush();context.document.hidden=true;events.visibilitychange();
 assert.equal(get('surface-play')['aria-pressed'],'false');context.document.hidden=false;
 // Some individual missing sites do not imply an entire network is absent.
 const healthy={...old,stations:[station,airport,wisconet],networkHealth:old.networkHealth};
 viewer.showHealth(healthy,dataset);assert.match(get('surface-feed-status').className,/feed-health-reporting/);
 viewer.showHealth({...healthy,stations:[airport,wisconet]},dataset);
 assert.match(text('surface-feed-status'),/Networks with zero reports: MN_RWIS/);
 viewer.showHealth({...healthy,sourceHealth:[{source:'AWC METAR',status:'ok',reports:0}]},dataset);
 assert.match(text('surface-feed-status'),/IEM fallback/);
 assert.ok(!fs.readFileSync('static/index.html','utf8').includes('surface-points'));
 console.log('Surface-view checks passed: no station dots, independent 12-hour field history, playback, race protection, refresh preservation and whole-network warnings.');
})().catch(error=>{console.error(error);process.exitCode=1;});
