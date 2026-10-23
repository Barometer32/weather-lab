'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{},Math,Number};
vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);
const model=context.window.WeatherStationModel;
const station={tempF:46,dewpointF:41,wind:{speedMph:20,direction:90},skyCover:{code:'BKN',displayFraction:.75},layers:[{cover:'BKN',baseFtAGL:2700}]};
const svg=model.stationModel(station);
assert.match(svg,/rotate\(270\)/); // Wind from east flows west.
assert.match(svg,/class="plot-temp"[^>]*>46<\/text>/);
assert.match(svg,/class="plot-dew"[^>]*>41<\/text>/);
assert.match(svg,/class="plot-speed" x="36" y="28.5" text-anchor="middle">20<\/text>/);
assert.doesNotMatch(svg,/plot-sky|plot-ceiling|<circle|BKN|2700/,'weather plot has no cloud symbol, coverage or height');
assert.equal(model.cloudHeightText(station),'3');
for(const [ft,label] of [[0,'1'],[100,'1'],[999,'1'],[1000,'1'],[1499,'1'],[1500,'2'],[12000,'12'],[25000,'25']]){
 assert.equal(model.cloudHeightText({...station,layers:[{cover:'OVC',baseFtAGL:ft}]}),label);
}
assert.equal(model.cloudHeightText({...station,layers:[{cover:'SCT',baseFtAGL:1000},{cover:'OVC',baseFtAGL:10000},{cover:'BKN',baseFtAGL:5000}]}),'5','use lowest BKN/OVC, excluding lower SCT');
for(const cover of ['FEW','SCT','CLR','VV'])assert.equal(model.cloudHeightText({...station,layers:[{cover,baseFtAGL:500}]}),'');
for(const baseFtAGL of [null,undefined,NaN,-100])assert.equal(model.cloudHeightText({...station,layers:[{cover:'BKN',baseFtAGL}]}),'');
assert.equal(model.cloudHeightText({...station,cloudLayers:[],layers:[{cover:'OVC',baseFtAGL:25000}]}),'25','empty cloudLayers falls back to legacy layers');
assert.equal(model.cloudHeightText({...station,cloudLayers:[{cover:'BKN',baseFtAGL:12000}]}),'12');
for(const speedMph of [0,.4]){
 const calm=model.stationModel({...station,wind:{speedMph}});
 assert.match(calm,/class="plot-speed"[^>]*>0<\/text>/);
 assert.doesNotMatch(calm,/Calm|calm-ring|plot-wind-state|wind-arrow/);
}
assert.match(model.stationModel({...station,wind:{speedMph:10,direction:null,variable:true}}),/>VRB<\/text>/);
assert.match(model.stationModel({...station,wind:{speedMph:null}}),/>\?<\/text>/);
assert.match(model.stationModel({...station,wind:{speedMph:100,direction:0}}),/style="font-size:10px">100/);
const anchors=html=>[...html.matchAll(/class="(plot-temp|plot-dew|plot-speed)" x="([^"]+)" y="([^"]+)"/g)].map(m=>m.slice(1)).sort();
const fixed=anchors(svg);
for(let direction=0;direction<360;direction+=5){
 const result=model.stationModel({...station,wind:{speedMph:20,direction}});
 assert.ok(result.includes(`rotate(${(direction+180)%360})`));
 assert.deepEqual(anchors(result),fixed,'wind rotation never moves a value');
 const a=(direction+180)*Math.PI/180;
 for(const [x,y,halo] of [[0,-14.5,2.5],[0,-17,2.5],[0,-20,.8],[-3.2,-14.8,.8],[3.2,-14.8,.8]]){
  const arrowX=36+x*Math.cos(a)-y*Math.sin(a);
  assert.ok(arrowX-halo>14.5,'arrow and halo clear left-hand values');
  assert.ok(Math.hypot(x,y)-halo>Math.hypot(9,7.5),'arrow clears centered wind number at every rotation');
 }
}
const changedClouds=model.stationModel({...station,skyCover:{code:'CLR',displayFraction:0},layers:[]});
assert.equal(changedClouds,svg,'cloud changes do not affect the METAR plot or spacing');
console.log('Weather-only station checks passed: centered wind arrow, fixed temperatures, calm/unknown states and cloud-height units/filtering.');
