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
 const boxes=(s,clouds)=>{const m=context.window.WeatherStationModel,p=point([s.lat,s.lon]);return (clouds?[m.cloudFootprint(s)]:m.combinedCollisionBoxes(s,{dot:true,mphBarbs:true})).filter(b=>b.kind!=='barb'||/class="wind-barb"|class="plot-wind-state"/.test(shown.get(s.station).icon.html)).map(b=>({...b,left:b.left+p.x,right:b.right+p.x,top:b.top+p.y,bottom:b.bottom+p.y}));};
 return {async load(){context.window.WeatherMetars.select('metar');await new Promise(setImmediate);},ids:()=>[...shown.keys()].sort(),barb(id){return shown.get(id)?.icon.html.includes('class="wind-barb"');},popup(id){return shown.get(id)?.popup;},mode(value){get('metar-product').events.change({target:{value}});},zoom(value){zoom=value;events.moveend();},frame(value){get('metar-timeline').events.input({target:{value:String(value)}});},check(clouds=false){
  for(let h=0;h<4;h++){
   this.frame(h);
   const rows=data.history[h].stations.filter(s=>shown.has(s.station));
   for(let i=0;i<rows.length;i++)for(let j=0;j<i;j++)assert.ok(!boxes(rows[i],clouds).some(a=>boxes(rows[j],clouds).some(b=>overlap(a,b)&&!((a.kind==='barb'&&b.kind!=='text')||(b.kind==='barb'&&a.kind!=='text')))),`${rows[i].station} overlaps ${rows[j].station} in frame ${h}`);
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
 await dense.load();assert.deepEqual(dense.ids(),['KMSP','KOTHER'],'painted shapes allow denser plots than enclosing rectangles');dense.check();
 // Barbs alone can collide even when temperatures and dots are separated.
 const barb=viewer([{...station('KMSP',200,100),fixedDirection:0},{...station('KSTP',180,70),fixedDirection:90}]);
 await barb.load();assert.deepEqual(barb.ids(),['KMSP','KSTP'],'crossing wind shafts no longer hide stations');
 assert.ok(barb.barb('KMSP')&&barb.barb('KSTP'),'both crossing barbs remain visible');barb.check();
 const numbers=viewer([{...station('KMSP',200,100),fixedDirection:90},{...station('KSTP',200,140),fixedDirection:270}]);
 await numbers.load();assert.deepEqual(numbers.ids(),['KMSP','KSTP'],'barb-to-number conflicts must keep both station readings');
 assert.ok(!numbers.barb('KMSP')||!numbers.barb('KSTP'),'a barb covering another station number is suppressed');numbers.check();
 const tight=viewer(['KMSP','KFCM','KMIC'].map((id,i)=>({...station(id,200,[100,80,120][i]),wind:{speedMph:0}})));
 await tight.load();assert.deepEqual(tight.ids(),['KFCM','KMIC'],'a tight zoom keeps two clear preferred airports instead of one blocking both');tight.check();
 const packing=viewer(['KAAA','KBBB','KCCC'].map((id,i)=>({...station(id,200,[100,80,120][i]),wind:{speedMph:0}})));
 await packing.load();assert.deepEqual(packing.ids(),['KBBB','KCCC'],'least-conflicting stations fill the available space more densely');packing.check();
 const metro=[station('KSTP',44.9345,-93.06),station('KSGS',44.8571,-93.0329),station('KMSP',44.8831,-93.2289),station('KFCM',44.8272,-93.4571),station('KMIC',45.0619,-93.3539)];
 const fixture=JSON.parse(fs.readFileSync('tests/fixtures/metro-20261113-20z.json','utf8'));
 for(const width of [320,375,1870]){
  const actual=viewer([],{width,zoom:8,geographic:true,historyData:fixture});await actual.load();
  for(const z of [7.5,7.75,8,8.25,8.5,9]){
   actual.zoom(z);actual.check();
   for(let h=0;h<4;h++){actual.frame(h);for(const id of (z>=8?['KFCM','KMSP','KMIC']:['KFCM','KMSP']))assert.ok(actual.ids().includes(id),`${id} survives actual wind history on ${width}px at zoom ${z}`);}
  }
  actual.zoom(8);actual.frame(3);assert.equal(actual.barb('KFCM'),false,'KFCM stays visible where its NE barb would cover KMSP numbers');
  assert.match(actual.popup('KFCM').children.map(n=>n.textContent).join(' '),/Wind: 6 mph from 60°.*hidden at this zoom/,'the actual wind stays available in the popup');
  actual.zoom(9);assert.equal(actual.barb('KFCM'),true,'KFCM barb returns when zoom supplies room');
  assert.doesNotMatch(actual.popup('KFCM').children.map(n=>n.textContent).join(' '),/hidden at this zoom/,'the visibility-specific popup cache updates on zoom');
 }
 for(const width of [320,375]){
  const v=viewer(metro,{width,geographic:true});await v.load();
  for(const clouds of [false,true]){
   v.mode(clouds?'clouds':'plots');
   for(const z of [8.5,8.75,9,9.25,9.5,9.75,10]){
    v.zoom(z);v.check(clouds);
    if(z===9)for(const id of ['KMSP','KFCM','KMIC'])assert.ok(v.ids().includes(id),`${id} retained on ${width}px phone`);
    if(z===9.5)for(const id of ['KSTP','KSGS'])assert.ok(v.ids().includes(id),`${id} appears once its plot fits`);
   }
  }
 }
 console.log('Metro priority passed: 320/375px phones, preferred airports, optional neighbors, dense empty-space packing, crossing barbs, protected readings, live KFCM regression and independent hourly reports.');
})().catch(error=>{console.error(error);process.exitCode=1;});
