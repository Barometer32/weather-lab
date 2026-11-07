'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function element(){return{value:'',events:{},children:[],hidden:false,disabled:false,textContent:'',style:{setProperty(){}},setAttribute(k,v){this[k]=v;},append(...v){this.children.push(...v);},addEventListener(k,f){this.events[k]=f;}};}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
const stations=[{station:'KFCM',lat:3,lon:1,time:'2026-10-24T17:53:00Z',reportType:'METAR',tempF:71,dewpointF:50,wind:{speedMph:7,direction:270},layers:[{cover:'BKN',baseFtAGL:2700}]},{station:'KNEAR',lat:3.01,lon:1,time:'2026-10-24T17:53:00Z',reportType:'METAR',tempF:70,dewpointF:49,wind:{speedMph:0},layers:[{cover:'CLR',baseFtAGL:null}]},{station:'KMSP',lat:9,lon:2,time:'2026-10-24T17:53:00Z',reportType:'METAR',tempF:72,dewpointF:51,wind:{speedMph:10,direction:225},layers:[{cover:'OVC',baseFtAGL:25000}]}];
let data={checkedAt:'2026-10-24T18:01:00Z',serverTime:'2026-10-24T18:02:00Z',history:Array.from({length:12},(_,i)=>({hour:new Date(Date.UTC(2026,9,24,7+i)).toISOString(),stations:stations.map(s=>({...s,tempF:i===0?100:s.tempF}))}))};
let reads=0,fail=false,shown=[],zoomed=false,fullConfig,subscriber,created=0,footprints=0;const callbacks={};
const map={setView(){return this;},getSize(){return{x:1000,y:700};},on(name,fn){callbacks[name]=fn;},latLngToContainerPoint([lat,lon]){return{x:zoomed?(lat-3)*6000+100:lat*50,y:lon*50};},invalidateSize(){}};
const context={window:{WeatherPrepared:{read:async()=>{reads++;if(fail)throw Error('Unavailable');return data;},subscribe(url,fn){assert.equal(url,'/api/station-plots?view=loop');subscriber=fn;}},WeatherFullscreen:{attach(c){fullConfig=c;}},WeatherSun:{sync(){}},addEventListener(){}},document:{getElementById:get,createElement:element,hidden:false},Intl,Math,Date,Number,Map,Set,setTimeout(){},setInterval(){},L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>({addTo(){return this;},clearLayers(){throw Error("Do not rebuild every marker on zoom");},removeLayer(marker){shown=shown.filter(s=>s!==marker);}}),divIcon:x=>x,marker:(position,config)=>{created++;return{position,...config,bindPopup(popup){this.popup=popup;return this;},addTo(){shown.push(this);return this;},setIcon(icon){this.icon=icon;return this;},setLatLng(position){this.position=position;return this;},setPopupContent(popup){this.popup=popup;return this;}};}}};
vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);const footprint=context.window.WeatherStationModel.combinedFootprint;context.window.WeatherStationModel.combinedFootprint=s=>{footprints++;return footprint(s);};vm.runInNewContext(fs.readFileSync('static/metar-views.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve)),ids=()=>shown.map(s=>s.title.split(' · ')[0]);
(async()=>{
 context.window.WeatherMetars.select('metar');await flush();
 assert.equal(shown.length,2,'Neighbouring combined station plots cannot overlap');
 assert.equal(reads,1);assert.equal(get('metar-timeline').max,'3');assert.equal(fullConfig.surfaceId,'metar-surface');
 const firstMarker=shown[0],initialFootprints=footprints;
 callbacks.moveend();assert.equal(created,2,'Existing markers survive map movement');assert.equal(shown[0],firstMarker);assert.equal(footprints,initialFootprints,'Four-frame footprints are cached until new data arrives');
 const svg=shown[0].icon.html;
 for(const cls of ['combined-station-plot','plot-temp','plot-dew','mesonet-dot','wind-barb'])assert.ok(svg.includes(cls),cls);
 assert.doesNotMatch(svg,/plot-speed|plot-ceiling|plot-sky|wind-calm/);
 assert.match(svg,/rotate\(270\)/,'A standard west-wind barb extends west toward the source');
 assert.deepEqual(Array.from(shown[0].position),[3,1],'Station circle is anchored to the exact airport');
 const popup=shown[0].popup.children.map(n=>n.textContent).join(' ');
 assert.match(popup,/Temperature: 71.0°F/);assert.match(popup,/Dewpoint: 50.0°F/);assert.match(popup,/Wind: 7 mph from 270°/);assert.match(popup,/BKN: 2,700 ft AGL/);
 get('metar-timeline').events.input({target:{value:'2'}});const before=ids();
 get('metar-timeline').events.input({target:{value:'0'}});assert.deepEqual(ids(),before,'History label changes keep density stable');assert.equal(reads,1,'Slider does not fetch source data');
 zoomed=true;callbacks.movestart();const duringMotion=created;get('metar-timeline').events.input({target:{value:'1'}});assert.equal(created,duringMotion,'No plot rebuild during a zoom gesture');callbacks.moveend();assert.ok(ids().includes('KNEAR'),'Zoom reveals nearby eligible airports');zoomed=false;
 get('metar-timeline').events.input({target:{value:'1'}});const hour=get('metar-time').textContent;
 data={...data,history:data.history.slice(1).concat({...data.history[11],hour:'2026-10-24T19:00:00Z'})};subscriber(data);assert.equal(get('metar-timeline').value,'0');assert.equal(get('metar-time').textContent,hour.replace('2/4','1/4'));
 const kept=ids();fail=true;get('refresh-metar').events.click();await flush();assert.deepEqual(ids(),kept);assert.match(get('metar-status').textContent,/Previous reports retained/);
 fail=false;
 get('metar-product').events.change({target:{value:'clouds'}});await flush();
 assert.deepEqual(ids(),['KFCM','KMSP'],'cloud circles and heights use nonoverlapping boxes');
 for(const marker of shown){
  assert.match(marker.icon.html,/class="plot-sky"/);
  assert.match(marker.icon.html,/class="plot-ceiling" x="20" y="12" text-anchor="start"/);
  assert.doesNotMatch(marker.icon.html,/plot-temp|wind-barb/);
 }
 zoomed=true;callbacks.moveend();
 const clear=shown.find(s=>s.title.startsWith('KNEAR ·'));
 assert.ok(clear,'clear-sky airports now remain eligible in CLOUDS');
 assert.match(clear.icon.html,/sky-outline/);assert.doesNotMatch(clear.icon.html,/sky-fill|plot-ceiling/);
 zoomed=false;callbacks.moveend();const cloudIds=ids();
 get('metar-timeline').events.input({target:{value:'0'}});assert.deepEqual(ids(),cloudIds,'cloud station density is stable across the loop');
 const extra=(station,lat,lon,layers)=>({station,lat,lon,layers,tempF:60,dewpointF:50});
 data={...data,history:data.history.map((frame,i)=>({...frame,stations:frame.stations.concat(
  extra('KUNKNOWN',12,3,[]),
  extra('KBASE',14,5,[{cover:'BKN',baseFtAGL:null}]),
  extra('KSWITCH',16,7,i===data.history.length-4?[]:[{cover:'OVC',baseFtAGL:2000}]),
  extra('KVALID',18,9,[{cover:'SCT',baseFtAGL:4000}])
 )}))};subscriber(data);
 assert.ok(ids().includes('KVALID'),'valid scattered cover needs no ceiling height');
 for(let i=0;i<4;i++){
  get('metar-timeline').events.input({target:{value:String(i)}});
  for(const id of ['KUNKNOWN','KBASE'])assert.ok(!ids().includes(id),'a station with no usable cloud data stays hidden: '+id);
  assert.ok(!ids().includes('KSWITCH'),'a missing cloud report removes the airport from every cloud frame');
  assert.ok(shown.every(s=>!s.icon.html.includes('?')),'no question-mark cloud markers remain');
 }
 get('metar-product').events.change({target:{value:'plots'}});await flush();
 for(const id of ['KUNKNOWN','KBASE','KSWITCH'])assert.ok(ids().includes(id),'cloud availability does not remove temperature/wind plots: '+id);
 console.log('Combined METAR view passed: one plot, exact anchors, standard barbs, collision spacing, stable timeline, zoom and refresh retention.');
})().catch(e=>{console.error(e);process.exitCode=1;});
