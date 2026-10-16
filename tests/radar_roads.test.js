"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let zoom=8,style,event,geometry,options;
const pane={style:{}},map={createPane(){return pane;},getZoom(){return zoom;},on(name,fn){event=fn;},attributionControl:{addAttribution(){}}};
const data=JSON.parse(fs.readFileSync('static/radar-highways.geojson','utf8'));
const context={window:{},fetch:async url=>{assert.equal(url,'/static/radar-highways.geojson');return {ok:true,json:async()=>data};},
 L:{canvas:()=>({}),geoJSON(d,o){geometry=d;options=o;style=o.style;return {addTo(){return this;},setStyle(fn){style=fn;}};}}};
vm.runInNewContext(fs.readFileSync('static/radar-roads.js','utf8'),context);
(async()=>{
 await context.window.WeatherRadarRoads.addTo(map);
 assert.equal(pane.style.zIndex,390);assert.equal(pane.style.pointerEvents,'none');
 assert.equal(options.interactive,false);
 assert.deepEqual(geometry.features.map(f=>f.properties.class),['I','U','S']);
 const f=c=>({properties:{class:c}});
 assert.ok(style(f('I')).opacity<.35);assert.ok(style(f('U')).opacity<.25);
 assert.equal(style(f('S')).opacity,0);zoom=9;event();assert.equal(style(f('S')).opacity,.15);
 for(const feature of geometry.features){assert.equal(feature.geometry.type,'MultiLineString');assert.deepEqual(Object.keys(feature.properties),['class']);}
 console.log('Highway checks passed: bundled lines only, no labels or markers, faint styling and zoom-dependent state roads.');
})().catch(e=>{console.error(e);process.exitCode=1;});
