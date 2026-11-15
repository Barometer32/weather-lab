'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function run(width){
 const nodes=new Map(),shown=new Map(),intervals=[],events={};let subscriber,center=[44.945,-93.343],zoom=9;
 const element=()=>({hidden:false,children:[],events:{},textContent:'',setAttribute(k,v){this[k]=v;},append(...v){this.children.push(...v);},addEventListener(k,f){this.events[k]=f;}});
 const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
 const time=new Date(Math.floor((Date.now()-20*60000)/300000)*300000).toISOString();
 const station=(id,lat,lon,extra={})=>({station:id,state:'MN',name:id,lat,lon,time,reportType:'HFMETAR',tempC:-2,dewpointC:-5,tempF:999,dewpointF:999,wind:{speedMph:10,direction:315},...extra});
 const data={checkedAt:new Date().toISOString(),sourceDelayed:true,stations:[station('KFCM',44.8321,-93.4705),station('KMSP',44.8852,-93.2313),station('KMIC',45.0623,-93.3511),station('KSTP',44.935,-93.06),station('KANE',45.063,-93.352),station('KBAD',44.95,-93.1,{dewpointC:null}),station('KORD',44.8,-93.4,{state:'IL'})]};
 let model;
 const project=([lat,lon])=>{const w=256*2**zoom,p=([a,b])=>({x:(b+180)/360*w,y:(.5-Math.log((1+Math.sin(a*Math.PI/180))/(1-Math.sin(a*Math.PI/180)))/(4*Math.PI))*w});const a=p([lat,lon]),c=p(center);return{x:width/2+a.x-c.x,y:250+a.y-c.y};};
 const map={getSize(){return{x:width,y:500};},setView(c,z){center=c;zoom=z;},latLngToContainerPoint:project,on(k,f){events[k]=f;},invalidateSize(){},getCenter(){return{lat:center[0],lng:center[1]};},getZoom(){return zoom;}};
 const context={window:{localStorage:{removeItem(){},getItem(){return null;}},WeatherPrepared:{subscribe(url,fn){assert.equal(url,'/api/rapmet');subscriber=fn;},async read(url){assert.equal(url,'/api/rapmet');return data;}},WeatherFullscreen:{attach(){}},addEventListener(){},WeatherSun:{sync(){}}},document:{getElementById:get,createElement:element,hidden:false},Date,Intl,Math,Number,Map,Set,setTimeout(){},setInterval(fn,ms){intervals.push(ms);},L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>({addTo(){return this;},removeLayer(m){shown.delete(m.title.split(' · ')[0]);}}),divIcon:x=>x,marker:(position,config)=>({position,...config,bindPopup(p){this.popup=p;return this;},addTo(){shown.set(this.title.split(' · ')[0],this);return this;},setIcon(i){this.icon=i;return this;},setLatLng(){return this;},setPopupContent(p){this.popup=p;return this;}})}};
 for(const f of ['metar-model','default-views','rapmet-views'])vm.runInNewContext(fs.readFileSync('static/'+f+'.js','utf8'),context);
 context.window.WeatherRapmet.select('rapmet');
 return new Promise(setImmediate).then(()=>{
  for(const id of ['KMSP','KFCM','KMIC'])assert.ok(shown.has(id),width+'px preferred '+id);
  for(const id of ['KSTP','KBAD','KORD','KANE'])assert.ok(!shown.has(id),'Excluded/overlapping/incomplete '+id);
  assert.ok(intervals.includes(300000),'Five-minute refresh interval');
  const msp=shown.get('KMSP');assert.doesNotMatch(msp.icon.html,/>999</);assert.match(msp.icon.html,/>-2</);assert.ok(msp.popup.children.some(n=>n.textContent==='Temperature: -2°C'));
  assert.match(get('rapmet-time').textContent,/°C · mph/);assert.match(get('rapmet-time').textContent,/Source delayed/);
  const preferred=['KMSP','KFCM','KMIC'];
  for(let z=5;z<=13;z+=.25)for(const id of preferred){
   const station=data.stations.find(s=>s.station===id);map.setView([station.lat,station.lon],z);events.moveend();
   for(const other of preferred){
    const s=data.stations.find(s=>s.station===other),p=project([s.lat,s.lon]);
    if(p.x>=0&&p.x<=width&&p.y>=0&&p.y<=500)assert.ok(shown.has(other),width+'px zoom '+z+' must retain '+other+' despite overlap');
   }
  }
  map.setView([44.945,-93.343],5);events.moveend();
  for(const id of preferred)assert.ok(shown.has(id),'All three remain plotted together at minimum zoom');
  subscriber({...data,checkedAt:new Date(Date.now()+1).toISOString(),stations:data.stations.filter(s=>s.station!=='KMIC')});
  assert.ok(!shown.has('KMIC'),'Always-visible preference never invents a missing report');
  context.window.WeatherRapmet.select('plots');subscriber({...data,stations:[]});assert.ok(shown.has('KMSP'),'Inactive RAPMET cannot draw over hourly map');
 });
}
(async()=>{for(const width of [320,375,1366])await run(width);console.log('RAPMET passed: Celsius-only plots, metro priority on phones, complete measurements, KSTP exclusion, real times and five-minute refresh.');})().catch(e=>{console.error(e);process.exitCode=1;});
