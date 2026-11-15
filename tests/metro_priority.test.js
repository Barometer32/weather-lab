'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function viewer(stations,{width=375,height=560,zoom=9,geographic=false,historyData=null}={}){
 const nodes=new Map(),shown=new Map(),events={};let subscriber;
 const element=()=>({value:'',hidden:false,children:[],events:{},style:{setProperty(){}},setAttribute(){},append(...v){this.children.push(...v);},addEventListener(k,f){this.events[k]=f;}});
 const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
 const project=(lat,lon,z)=>{const world=256*2**z,s=Math.sin(lat*Math.PI/180);return{x:(lon+180)/360*world,y:(.5-Math.log((1+s)/(1-s))/(4*Math.PI))*world};};
 const point=([lat,lon])=>{if(!geographic)return{x:lon,y:lat};const p=project(lat,lon,zoom),c=project(44.945,-93.343,zoom);return{x:p.x-c.x+width/2,y:p.y-c.y+height/2};};
 const map={setView(){return this;},getSize(){return{x:width,y:height};},latLngToContainerPoint:point,on(k,f){events[k]=f;},invalidateSize(){}};
 const data=historyData||{checkedAt:'2026-11-13T17:10:00Z',history:Array.from({length:4},(_,i)=>({hour:new Date(Date.UTC(2026,10,13,14+i)).toISOString(),stations:stations.map(s=>({...s,wind:{...s.wind,direction:s.fixedDirection??(i%2?180:0)}}))}))};
 const context={window:{WeatherPrepared:{read:async()=>data,subscribe(_,fn){subscriber=fn;}},WeatherFullscreen:{attach(){}},addEventListener(){}},document:{getElementById:get,createElement:element,hidden:false},Intl,Math,Number,Date,Map,Set,WeakMap,setTimeout(){},setInterval(){},L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>({addTo(){return this;},removeLayer(m){shown.delete(m.title.split(' · ')[0]);}}),divIcon:x=>x,marker:(position,opts)=>({position,...opts,bindPopup(value){this.popup=value;return this;},addTo(){shown.set(this.title.split(' · ')[0],this);return this;},setIcon(v){this.icon=v;return this;},setLatLng(v){this.position=v;return this;},setPopupContent(value){this.popup=value;return this;}})}};
 for(const file of ['metar-model','metar-views'])vm.runInNewContext(fs.readFileSync('static/'+file+'.js','utf8'),context);
 const overlap=(a,b)=>a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;
 const boxes=(s,clouds)=>{const m=context.window.WeatherStationModel,p=point([s.lat,s.lon]);return (clouds?[m.cloudFootprint(s)]:m.combinedCollisionBoxes(s,{dot:true,mphBarbs:true})).map(b=>({...b,left:b.left+p.x,right:b.right+p.x,top:b.top+p.y,bottom:b.bottom+p.y}));};
 return {async load(){context.window.WeatherMetars.select('metar');await new Promise(setImmediate);},ids:()=>[...shown.keys()].sort(),barb(id){return shown.get(id)?.icon.html.includes('class="wind-barb"');},popup(id){return shown.get(id)?.popup;},mode(value){get('metar-product').events.change({target:{value}});},zoom(value){zoom=value;events.moveend();},frame(value){get('metar-timeline').events.input({target:{value:String(value)}});},check(clouds=false){
  for(let h=0;h<4;h++){
   this.frame(h);
   const rows=data.history[h].stations.filter(s=>shown.has(s.station));
   if(!clouds)for(const station of rows){
    const wind=context.window.WeatherStationModel.combinedWind(station.wind,true);
    if(wind.kind==='barb')assert.ok(this.barb(station.station),`${station.station} cannot appear without its full barb`);
   }
   for(let i=0;i<rows.length;i++)for(let j=0;j<i;j++)assert.ok(!boxes(rows[i],clouds).some(a=>boxes(rows[j],clouds).some(b=>overlap(a,b)&&a.kind!=='barb'&&b.kind!=='barb')),`${rows[i].station} overlaps ${rows[j].station} in frame ${h}`);
  }
 },adopt:subscriber,model:context.window.WeatherStationModel};
}
const station=(station,lat,lon)=>({station,lat,lon,tempF:35,dewpointF:22,wind:{speedMph:10},layers:[{cover:'BKN',baseFtAGL:2200}]});
(async()=>{
 // Adversarial ordering: optional airports at identical anchors must lose to
 // the preferred trio in both products, even on a narrow phone.
 const crowded=viewer([station('KSTP',140,100),station('KSGS',220,100),station('KAAA',300,100),station('KMSP',140,100),station('KFCM',220,100),station('KMIC',300,100)],{width:320});
 await crowded.load();assert.deepEqual(crowded.ids(),['KFCM','KMIC','KMSP']);crowded.check();
 crowded.mode('clouds');assert.deepEqual(crowded.ids(),['KFCM','KMIC','KMSP']);crowded.check(true);
 // Empty corners of an enclosing rectangle are usable map space. Each same-
 // hour north/south barb is clear, despite the combined four-hour envelope.
 const dense=viewer([station('KMSP',200,100),station('KOTHER',200,135)]);
 await dense.load();assert.deepEqual(dense.ids(),['KMSP'],'a neighbor inside the potential wind sweep is never temporarily admitted');dense.check();
 // Barbs alone can collide even when temperatures and dots are separated.
 const barb=viewer([{...station('KMSP',200,100),fixedDirection:0},{...station('KSTP',180,70),fixedDirection:90}]);
 await barb.load();assert.deepEqual(barb.ids(),['KMSP'],'potential rotation is reserved even when current barbs only cross each other');
 assert.ok(barb.barb('KMSP'),'the preferred station keeps its complete barb');barb.check();
 const crossing=viewer([{...station('KMSP',200,100),fixedDirection:90},{...station('KSTP',220,170),fixedDirection:270}]);
 await crossing.load();assert.deepEqual(crossing.ids(),['KMSP','KSTP'],'barb-to-barb crossings remain allowed when neither potential sweep reaches numbers');
 assert.ok(crossing.barb('KMSP')&&crossing.barb('KSTP'));crossing.check();
 const numbers=viewer([{...station('KMSP',200,100),fixedDirection:90},{...station('KSTP',200,140),fixedDirection:270}]);
 await numbers.load();assert.deepEqual(numbers.ids(),['KMSP'],'barb-to-number conflicts remove the entire lower-priority plot');
 assert.ok(numbers.barb('KMSP'),'a displayed plot keeps its entire wind barb');numbers.check();
 for(let angle=0;angle<360;angle+=5){
  const bearing=viewer([{...station('KMSP',250,130),fixedDirection:angle},{...station('KSTP',235,160),fixedDirection:(angle+180)%360}]);
  await bearing.load();bearing.check();assert.ok(bearing.barb('KMSP'),'priority airport retains its full rotated barb');
 }
 const blaineSource=JSON.parse(fs.readFileSync('tests/fixtures/metro-20261113-21z.json','utf8'));
 for(const width of [320,375,1870]){
  const reserved=viewer([],{width,zoom:8,geographic:true,historyData:blaineSource});await reserved.load();
  const roster=reserved.ids();assert.ok(roster.includes('KMIC'),'KMIC wins the contested space');
  assert.ok(!roster.includes('KANE'),"Blaine is excluded from KMIC's potential wind sweep");
  for(let h=0;h<4;h++){reserved.frame(h);assert.deepEqual(reserved.ids(),roster,'calm/VRB/directional hourly changes cannot admit Blaine');}
  for(const wind of [{speedMph:0,direction:null},{speedMph:4,variable:true},...Array.from({length:24},(_,i)=>({speedMph:8,direction:i*15}))]){
   const variant=JSON.parse(JSON.stringify(blaineSource));
   for(const frame of variant.history)frame.stations.find(s=>s.station==='KMIC').wind=wind;
   reserved.adopt(variant);
   for(let h=0;h<4;h++){reserved.frame(h);assert.deepEqual(reserved.ids(),roster,'full-sweep selection cannot depend on current bearing or calm wind');}
  }
  const gap=JSON.parse(JSON.stringify(blaineSource));gap.history[1].stations=gap.history[1].stations.filter(s=>s.station!=='KMIC');reserved.adopt(gap);
  for(let h=0;h<4;h++){
   reserved.frame(h);assert.ok(!reserved.ids().includes('KANE'),'a missing KMIC report never gives Blaine temporary space');
   assert.equal(reserved.ids().includes('KMIC'),h!==1,'only the missing hour lacks the actual KMIC plot');
  }
  const absent=JSON.parse(JSON.stringify(blaineSource));for(const frame of absent.history)frame.stations=frame.stations.filter(s=>s.station!=='KMIC');reserved.adopt(absent);
  for(let h=0;h<4;h++){reserved.frame(h);assert.ok(!reserved.ids().includes('KANE'),'priority layout space remains reserved during an outage');assert.ok(!reserved.ids().includes('KMIC'),'a layout placeholder never becomes a weather report');}
  reserved.adopt(blaineSource);reserved.zoom(10);assert.ok(reserved.ids().includes('KANE'),'Blaine returns when the reserved areas have room');reserved.check();
 }
 const tight=viewer(['KMSP','KFCM','KMIC'].map((id,i)=>({...station(id,200,[100,50,150][i]),wind:{speedMph:0}})));
 await tight.load();assert.deepEqual(tight.ids(),['KFCM','KMIC'],'a tight zoom keeps two clear preferred airports instead of one blocking both');tight.check();
 const packing=viewer(['KAAA','KBBB','KCCC'].map((id,i)=>({...station(id,200,[100,50,150][i]),wind:{speedMph:0}})));
 await packing.load();assert.deepEqual(packing.ids(),['KBBB','KCCC'],'least-conflicting stations fill the available space more densely');packing.check();
 const metro=[station('KSTP',44.9345,-93.06),station('KSGS',44.8571,-93.0329),station('KMSP',44.8831,-93.2289),station('KFCM',44.8272,-93.4571),station('KMIC',45.0619,-93.3539)];
 const fixture=JSON.parse(fs.readFileSync('tests/fixtures/metro-20261113-20z.json','utf8'));
 for(const width of [320,375,1870]){
  const actual=viewer([],{width,zoom:8,geographic:true,historyData:fixture});await actual.load();
  for(const z of [7.5,7.75,8,8.25,8.5,9]){
   actual.zoom(z);actual.check();
   for(let h=0;h<4;h++){actual.frame(h);if(z>=9)for(const id of ['KFCM','KMSP','KMIC'])assert.ok(actual.ids().includes(id),`${id} appears with room for its full plot on ${width}px at zoom ${z}`);}
  }
  actual.zoom(8);actual.frame(3);assert.ok(!(actual.ids().includes('KFCM')&&actual.ids().includes('KMSP')),'a barb-to-number conflict cannot leave both full station plots visible');
  if(actual.ids().includes('KFCM'))assert.ok(actual.barb('KFCM'),'KFCM is never squeezed in without its barb');
  actual.zoom(9);assert.ok(actual.ids().includes('KFCM')&&actual.barb('KFCM'),'the complete KFCM plot returns when zoom supplies room');
  assert.match(actual.popup('KFCM').children.map(n=>n.textContent).join(' '),/Wind: 6 mph from 60°/);

 }
 for(const width of [320,375]){
  const v=viewer(metro,{width,geographic:true});await v.load();
  for(const clouds of [false,true]){
   v.mode(clouds?'clouds':'plots');
   for(const z of [8.5,8.75,9,9.25,9.5,9.75,10]){
    v.zoom(z);v.check(clouds);
    if(z===9)for(const id of ['KMSP','KFCM','KMIC'])assert.ok(v.ids().includes(id),`${id} retained on ${width}px phone`);
    if(z===9.5&&clouds)for(const id of ['KSTP','KSGS'])assert.ok(v.ids().includes(id),`${id} appears when its cloud plot fits`);
    if(z===9.5&&!clouds)assert.ok(['KSTP','KSGS'].some(id=>v.ids().includes(id)),'optional airports remain eligible when their wind reservations fit');
   }
  }
 }
 console.log('Metro priority passed: 320/375px phones, preferred airports, optional neighbors, dense empty-space packing, crossing barbs, separated numeric labels, full-sweep KMIC/Blaine stability, priority outage reservations and independent hourly reports.');
})().catch(error=>{console.error(error);process.exitCode=1;});
