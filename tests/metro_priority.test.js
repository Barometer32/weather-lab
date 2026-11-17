'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),viewer=require('./metro_viewer');
// Golden output captured from the pre-average CLOUDS implementation (aea98ac).
// Covers both real metro fixtures, every frame, phone/desktop widths and zooms.
(async()=>{
 const hash=crypto.createHash('sha256');
 for(const file of ['metro-20261113-20z.json','metro-20261113-21z.json'])for(const width of [320,375,1870]){
  const data=JSON.parse(fs.readFileSync('tests/fixtures/'+file));
  const v=viewer(data,{history:[]},{width});await v.load();
  for(const zoom of [7.5,8,8.5,9,9.5,10,12]){
   v.zoom(zoom);
   for(let frame=0;frame<4;frame++){
    v.frame(frame);hash.update(JSON.stringify({file,width,zoom,frame,plots:v.snapshot()}));
    assert.ok(!v.ids().includes('METRO'),'CLOUDS never uses the combined PLOTS average');
   }
  }
 }
 assert.equal(hash.digest('hex'),'834ae2e7f761c94eb6872687a1f78ee382eee48d436e5935e118236ac85d7d2a',
  'CLOUDS selection, priority, geographic anchors, icons and popups exactly match the previous release');
 console.log('CLOUDS unchanged: 168 frame/zoom/viewport comparisons match the previous release exactly.');
})().catch(error=>{console.error(error);process.exitCode=1;});
