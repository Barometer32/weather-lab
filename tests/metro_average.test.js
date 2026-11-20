'use strict';
const assert=require('node:assert/strict'),viewer=require('./metro_viewer');
const core=['KMSP','KFCM','KMIC'],locations=[[44.8831,-93.2289],[44.8272,-93.4571],[45.0619,-93.3539]];
const history=Array.from({length:4},(_,i)=>({hour:new Date(Date.UTC(2026,10,17,15+i)).toISOString(),stations:[
 ...core.map((station,j)=>({station,lat:locations[j][0],lon:locations[j][1],time:'2026-11-17T17:53:00Z',tempF:80+j,dewpointF:60+j,wind:{speedMph:15,direction:270},layers:[{cover:'BKN',baseFtAGL:2000+j*1000}]})),
 {station:'KSTP',lat:44.9345,lon:-93.06,tempF:60,dewpointF:40,wind:{speedMph:5,direction:90},layers:[{cover:'CLR'}]}
]}));
const data={checkedAt:'2026-11-17T18:02:00Z',history},
 current={checkedAt:'2026-11-17T18:03:00Z',history:history.map((f,i)=>({hour:f.hour,complete:true,tempF:40+i,dewpointF:20+i,wind:{speedMph:i===0?3:7,direction:350,speedCount:3}})).reverse()};
current.current=current.history[0];
const popup=m=>m.popup.children.map(n=>n.textContent).join(' ');
(async()=>{
 const originals=JSON.stringify({data,current});
 for(const width of [320,375,1870]){
  const v=viewer(data,current,{width,zoom:9});await v.load();
  assert.ok(v.ids().includes('METRO'),'the three-airport average appears on the opening map');
  await v.mode('clouds');
  const clouds=v.snapshot();for(const id of core)assert.ok(v.ids().includes(id),'CLOUDS retains '+id);
  await v.mode('plots');
  for(const z of [7.5,8,8.5,9,10]){
   v.zoom(z);
   for(let i=0;i<4;i++){
    v.frame(i);assert.ok(v.ids().includes('METRO'),'average has first priority on phone and desktop maps');
    assert.ok(core.every(id=>!v.ids().includes(id)),'individual trio is replaced only in PLOTS');
    const m=v.marker('METRO'),row=current.history.find(r=>r.hour===history[i].hour);
    assert.ok(Math.abs(m.position[0]-locations.reduce((a,p)=>a+p[0]/3,0))<1e-10);
    assert.ok(Math.abs(m.position[1]-locations.reduce((a,p)=>a+p[1]/3,0))<1e-10);
    assert.match(m.icon.html,new RegExp('class="plot-temp"[^>]*>'+row.tempF+'</text>'));
    assert.match(m.icon.html,new RegExp('class="plot-dew"[^>]*>'+row.dewpointF+'</text>'));
    assert.match(popup(m),/KMSP \/ KFCM \/ KMIC average/);assert.doesNotMatch(popup(m),/Cloud cover|No BKN/);
    assert.match(popup(m),i===0?/Wind: CALM/:/Wind: N 7 mph/);
    assert.equal(m.icon.html.includes('class="wind-barb"'),i!==0,'CALM threshold matches CURRENT');
   }
  }
  v.zoom(9);v.frame(3);
  assert.ok(popup(v.marker('METRO')).includes(`Temperature: ${current.current.tempF.toFixed(1)}°F`));
  assert.ok(popup(v.marker('METRO')).includes(`Dewpoint: ${current.current.dewpointF.toFixed(1)}°F`));
  v.failCurrent();await v.refresh();assert.ok(v.ids().includes('METRO'),'transient CURRENT failure retains prepared average');
  const partial=JSON.parse(JSON.stringify(current));partial.checkedAt='2026-11-17T18:04:00Z';partial.history[0].complete=false;
  v.adoptCurrent(partial);assert.ok(!v.ids().includes('METRO'),'no partial average or prior-hour substitution');
  v.frame(2);assert.ok(v.ids().includes('METRO'),'only the incomplete hour is omitted');
  v.frame(3);v.adoptCurrent({...current,checkedAt:'2026-11-17T18:05:00Z'});assert.ok(v.ids().includes('METRO'),'late complete CURRENT average fills the matching hour');
  v.adoptCurrent(partial);assert.ok(v.ids().includes('METRO'),'older CURRENT response cannot erase newer average');
  await v.mode('clouds');assert.deepEqual(v.snapshot(),clouds,'CLOUDS markers, positions, symbols, popup content and priorities remain unchanged');
  const before=v.snapshot();v.adoptCurrent({...current,checkedAt:'2026-11-17T18:06:00Z'});assert.deepEqual(v.snapshot(),before,'CURRENT arrivals never redraw CLOUDS');
  await v.mode('plots');v.zoom(9);assert.ok(v.ids().includes('KSTP'),'other airports remain individual plots');
 }
 assert.equal(JSON.stringify({data,current}),originals,'shared CURRENT and CLOUDS source data is never mutated');
 const empty=viewer(data,{history:[]},{zoom:9});await empty.load();await empty.mode('plots');assert.ok(!empty.ids().includes('METRO')&&core.every(id=>!empty.ids().includes(id)),'missing CURRENT never falls back to a partial or rounded-map average');
 console.log('Metro average passed: opening map, exact-hour matching, centroid, 320/375px and desktop maps, calm wind, delayed arrivals, failure retention and unchanged CLOUDS.');
})().catch(e=>{console.error(e);process.exitCode=1;});
