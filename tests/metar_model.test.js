'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{},Math,Number};
vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);
const model=context.window.WeatherStationModel;
const station={tempF:46,dewpointF:41,wind:{speedMph:20,direction:90},skyCover:{code:'BKN',displayFraction:.75},layers:[{cover:'BKN',baseFtAGL:2700}]};
const svg=model.stationModel(station);
assert.match(svg,/rotate\(270\)/,'easterly wind vector points downwind to the west');
assert.match(svg,/class="plot-temp"[^>]*>46<\/text>/);
assert.match(svg,/class="plot-dew"[^>]*>41<\/text>/);
assert.match(svg,/class="plot-speed" x="56.5" y="40" text-anchor="start">20<\/text>/);
assert.doesNotMatch(svg,/plot-sky|plot-ceiling|sky-fill/);
const cloudSvg=model.cloudStationModel(station);
assert.match(cloudSvg,/class="plot-ceiling" x="16" y="12" text-anchor="middle" dominant-baseline="central">3<\/text>/);
assert.doesNotMatch(cloudSvg,/plot-sky|sky-fill|plot-temp|plot-dew|plot-speed|wind-vector|cloud-dot/);
assert.match(svg,/class="wind-vector"/);assert.doesNotMatch(svg,/wind-barb|wind-flag|wind-shaft/);
assert.equal(Number(svg.match(/height="([^"]+)"/)[1]),model.iconSize[1],"ceiling label never changes SVG size");
for(const [ft,label] of [[0,'1'],[999,'1'],[1000,'1'],[1499,'1'],[1500,'2'],[12000,'12'],[25000,'25']]){
 assert.equal(model.cloudHeightText({...station,layers:[{cover:'OVC',baseFtAGL:ft}]}),label);
}
assert.equal(model.cloudHeightText({...station,layers:[{cover:'SCT',baseFtAGL:1000},{cover:'OVC',baseFtAGL:10000},{cover:'BKN',baseFtAGL:5000}]}),'5');
for(const cover of ['FEW','SCT','CLR','VV'])assert.equal(model.cloudHeightText({...station,layers:[{cover,baseFtAGL:500}]}),'');
for(const baseFtAGL of [null,undefined,NaN,-100]){
 assert.equal(model.cloudHeightText({...station,layers:[{cover:'BKN',baseFtAGL},{cover:'OVC',baseFtAGL:10000}]}),'','unknown ceiling base cannot be assumed above a known layer');
}
assert.equal(model.cloudHeightText({...station,cloudLayers:[],layers:[{cover:'OVC',baseFtAGL:25000}]}),'25');
assert.equal(model.cloudHeightText({...station,cloudLayers:[{cover:'BKN',baseFtAGL:12000}]}),'12');
for(const code of ['CLR','SKC','NSC','NCD','CAVOK','FEW','SCT','VV']){
 const dot=model.cloudStationModel({...station,skyCover:{code},layers:code==='VV'?[{cover:code,baseFtAGL:300}]:[{cover:code,baseFtAGL:1000}]});
 assert.match(dot,/class="cloud-dot" cx="16" cy="12" r="1.9"/);
 assert.doesNotMatch(dot,/plot-sky|plot-ceiling/);
}
const unknown=model.cloudStationModel({...station,skyCover:null,layers:[]});
assert.match(unknown,/plot-cloud-unknown[^>]*>\?<\/text>/);
assert.match(model.cloudStationModel({...station,layers:[{cover:'BKN',baseFtAGL:null}]}),/plot-cloud-unknown[^>]*>\?<\/text>/);
assert.match(model.cloudStationModel({...station,skyCover:{code:'BKN'},layers:[]}),/plot-cloud-unknown[^>]*>\?<\/text>/);
for(const speedMph of [0,.4]){
 const calm=model.stationModel({...station,wind:{speedMph}});
 assert.match(calm,/class="plot-speed"[^>]*>0<\/text>/);assert.doesNotMatch(calm,/plot-sky/);
 assert.doesNotMatch(calm,/Calm|plot-wind-state|wind-vector/);
}
assert.match(model.stationModel({...station,wind:{speedMph:10,direction:null,variable:true}}),/>VRB<\/text>/);
assert.match(model.stationModel({...station,wind:{speedMph:null}}),/>\?<\/text>/);
assert.match(model.stationModel({...station,wind:{speedMph:100,direction:0}}),/style="font-size:10px">100/);
const anchors=html=>[...html.matchAll(/class="(plot-temp|plot-dew|plot-speed|plot-ceiling)" x="([^"]+)" y="([^"]+)"/g)].map(m=>m.slice(1));
for(let direction=0;direction<360;direction+=5){
 const result=model.stationModel({...station,wind:{speedMph:20,direction}});
 const rotation=(direction+180)%360;
 assert.ok(result.includes(`rotate(${rotation})`));
 assert.deepEqual(anchors(result),anchors(svg),'rotating wind never moves temperature, dewpoint, ceiling or speed');
 const a=rotation*Math.PI/180;
 for(const [x,y] of [[0,-9.5],[4.5,-4],[1.3,5],[-1.3,5],[-4.5,-4]]){
  const arrowX=43+x*Math.cos(a)-y*Math.sin(a);
  assert.ok(arrowX-.8>31&&arrowX+.8<55,'arrow and halo clear all four text columns');
 }
}
for(const [source,destination] of [[0,180],[90,270],[180,0],[270,90]]){
 assert.match(model.stationModel({...station,wind:{speedMph:10,direction:source}}),new RegExp('rotate\\('+destination+'\\)'));
}
assert.equal(model.stationModel({...station,skyCover:{code:'CLR'},layers:[]}),svg,'cloud changes never affect the METAR glyph');
assert.deepEqual(model.footprint({...station,skyCover:null,layers:[]}),model.footprint(station),'cloud changes never affect METAR spacing');
console.log('Separate station checks passed: sky cover, lowest BKN/OVC, calm/unknown wind, downwind vectors and tighter fixed values.');
