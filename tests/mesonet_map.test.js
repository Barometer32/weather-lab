'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const urls={airport:'/api/station-plots?view=loop',mesonet:'/api/observation-stations?view=mesonet'};
const nodes=new Map(), shown=new Map(), timers=new Map(), subs=new Map(), requests=[];
function get(id){
  if(!nodes.has(id))nodes.set(id,{value:'',children:[],events:{},style:{setProperty(){}},
    append(...items){this.children.push(...items);},setAttribute(){},addEventListener(name,fn){this.events[name]=fn;}});
  return nodes.get(id);
}
const html=fs.readFileSync('static/index.html','utf8');
assert.match(html,/<option value="mesonet" selected>MESONET/);
assert.match(html,/id="sun-angle"/);
get('metar-product').value='mesonet';
const now=Date.now(),at=(minutes)=>new Date(now-minutes*60000).toISOString();
const station=(id,lat=3,extra={})=>({station:id,displayName:'Hopkins',time:at(10),lat,lon:2,
  tempF:40,dewpointF:35,wind:{speedMph:12,direction:270},layers:[{cover:'CLR'}],...extra});
let mesonet={stations:[station('HPN20'),station('HPN38',3.03,{wind:{speedMph:1,direction:180}}),station('HPN26',5,{time:at(61)})],
  bounds:[[1,1],[9,9]],checkedAt:at(1),serverTime:at(0)};
const airport={history:Array.from({length:4},(_,i)=>({hour:at((3-i)*60),stations:[station('KFCM')]}))};
let fits=0, zoom=9;
const map={fitBounds(points){fits++;this.points=points;zoom=11;return this;},setView(_center,z){zoom=z;return this;},
  getZoom(){return zoom;},getCenter(){return{lat:4,lng:2};},getSize(){return{x:1000,y:800};},
  latLngToContainerPoint([lat,lon]){return{x:lat*100,y:lon*100};},on(){},invalidateSize(){}};
const context={window:{WeatherPrepared:{async read(url){requests.push(url);return url===urls.mesonet?mesonet:airport;},
  subscribe(url,fn){subs.set(url,fn);}},WeatherFullscreen:{attach(){}},addEventListener(){}},
  document:{getElementById:get,createElement:()=>get(Symbol()),hidden:false},
  setInterval:(callback,ms)=>timers.set(ms,callback),setTimeout(){},
  L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>({addTo(){return this;},removeLayer(m){shown.delete(m.title);}}),
  divIcon:x=>x,marker:(_point,opts)=>({...opts,bindPopup(p){this.popup=p;return this;},
    addTo(){shown.set(this.title,this);return this;},setIcon(i){this.icon=i;return this;},setLatLng(){return this;},setPopupContent(){return this;}})}};
for(const path of ['static/metar-model.js','static/metar-views.js'])vm.runInNewContext(fs.readFileSync(path,'utf8'),context);
const flush=()=>new Promise(setImmediate),select=value=>get('metar-product').events.change({target:{value}});
(async()=>{
  context.window.WeatherMetars.select('metar');await flush();
  assert.deepEqual(requests,[urls.mesonet]);
  assert.deepEqual([...shown.keys()],['HPN20 · MESONET','HPN38 · MESONET'],'Nearby Mesonet stations are still plotted');
  assert.ok(get('metar-history').hidden);
  assert.equal(map.points.length,3); // Fit the available station extent before hiding overlapping labels.
  const marker=shown.get('HPN20 · MESONET');
  assert.match(marker.icon.html,/plot-temp/);
  assert.match(marker.icon.html,/plot-dew/);
  assert.match(marker.icon.html,/rotate\(270\)/);
  assert.match(shown.get('HPN38 · MESONET').icon.html,/data-mph="0"[^>]+rotate\(180\)/);
  assert.ok(marker.popup.children.some(n=>n.textContent.includes('Hopkins (HPN20)')));
  const originalFits=fits;
  mesonet={...mesonet,stations:[station('HPN20',3,{tempF:48}),station('HPN38',4)]};
  timers.get(300000)();await flush();
  assert.equal(requests.length,2);
  assert.match(shown.get('HPN20 · MESONET').icon.html,/>48</);
  assert.equal(fits,originalFits,'Refreshing readings does not reset zoom');
  select('plots');await flush();
  assert.deepEqual([...shown.keys()],['KFCM · METAR']);
  assert.equal(get('metar-history').hidden,false);
  assert.equal(get('metar-timeline').max,'3');
  const count=requests.length;timers.get(300000)();await flush();
  assert.equal(requests.length,count,'Mesonet polling stops in the airport mode');
  select('mesonet');await flush();
  assert.deepEqual([...shown.keys()],['HPN20 · MESONET','HPN38 · MESONET']);
  assert.equal(map.getZoom(),11,'The local view is restored after switching');
  console.log('Default Mesonet map, station plots, polling, and airport-mode isolation verified.');
})().catch(error=>{console.error(error);process.exitCode=1;});
