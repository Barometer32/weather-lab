'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{},Math,Number};
vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);
const model=context.window.WeatherStationModel;
const station={tempF:46,dewpointF:41,wind:{speedMph:20,direction:90},skyCover:{code:'BKN',displayFraction:.75},layers:[{cover:'BKN',baseFtAGL:2700}]};
const svg=model.stationModel(station);
assert.match(svg,/rotate\(90\)/,'easterly wind barb points toward its source to the east');
assert.match(svg,/class="plot-temp"[^>]*>46<\/text>/);
assert.match(svg,/class="plot-dew"[^>]*>41<\/text>/);
assert.match(svg,/class="plot-speed" x="79" y="49" text-anchor="start">20<\/text>/);
assert.match(svg,/class="plot-ceiling" x="79" y="22" text-anchor="start">3<\/text>/);
assert.match(svg,/class="plot-sky"/);assert.match(svg,/class="sky-fill"/);
assert.match(svg,/class="wind-barb"/);assert.doesNotMatch(svg,/wind-vector/);
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
for(const code of ['CLR','SKC','NSC','NCD','CAVOK']){
 const clear=model.stationModel({...station,skyCover:{code},layers:[]});
 assert.match(clear,/sky-outline/);assert.doesNotMatch(clear,/sky-fill|plot-ceiling|sky-obscured|plot-sky-unknown/);
}
const overcast=model.stationModel({...station,skyCover:{code:'OVC'}});
assert.match(overcast,/<circle class="sky-fill"/);
const obscure=model.stationModel({...station,skyCover:{code:'VV'},layers:[{cover:'VV',baseFtAGL:300}]});
assert.match(obscure,/sky-obscured/);assert.doesNotMatch(obscure,/plot-ceiling|sky-fill/);
assert.match(model.stationModel({...station,skyCover:null,layers:[]}),/plot-sky-unknown/);
for(const code of ['FEW','SCT','BKN'])assert.match(model.stationModel({...station,skyCover:null,layers:[{cover:code,baseFtAGL:1000}]}),/<path class="sky-fill"/);
for(const speedMph of [0,.4]){
 const calm=model.stationModel({...station,wind:{speedMph}});
 assert.match(calm,/class="plot-speed"[^>]*>0<\/text>/);assert.match(calm,/plot-sky/);
 assert.doesNotMatch(calm,/Calm|plot-wind-state|wind-barb/);
}
assert.match(model.stationModel({...station,wind:{speedMph:10,direction:null,variable:true}}),/>VRB<\/text>/);
assert.match(model.stationModel({...station,wind:{speedMph:null}}),/>\?<\/text>/);
assert.match(model.stationModel({...station,wind:{speedMph:100,direction:0}}),/style="font-size:10px">100/);
const anchors=html=>[...html.matchAll(/class="(plot-temp|plot-dew|plot-speed|plot-ceiling)" x="([^"]+)" y="([^"]+)"/g)].map(m=>m.slice(1));
for(let direction=0;direction<360;direction+=5){
 const result=model.stationModel({...station,wind:{speedMph:20,direction}});
 assert.ok(result.includes(`rotate(${direction})`));
 assert.deepEqual(anchors(result),anchors(svg),'rotating wind never moves temperature, dewpoint, ceiling or speed');
 // All barb vertices, including extreme winds, fit inside the label-free center.
 for(let knots=5;knots<=200;knots+=5){
  const rendered=model.stationModel({...station,wind:{speedKnots:knots,direction}});
  const group=rendered.split('<g class="wind-ink"')[1].split('</g>')[0];
  const vertices=[...group.matchAll(/(?:M|L)(-?[\d.]+) (-?[\d.]+)/g)].map(m=>[+m[1],+m[2]]);
  vertices.push([0,-20]);
  for(const [x,y] of vertices){
   const a=direction*Math.PI/180,rotatedX=51+x*Math.cos(a)-y*Math.sin(a);
   assert.ok(rotatedX-1.8>24.5&&rotatedX+1.8<77.5,'wind barb and halo clear all four text columns');
  }
 }
}
const fiveKnots=model.stationModel({...station,wind:{speedKnots:5,direction:0}});
const tenKnots=model.stationModel({...station,wind:{speedKnots:10,direction:0}});
assert.match(fiveKnots,/L3 /);assert.match(tenKnots,/L6 /);
assert.match(model.stationModel({...station,wind:{speedKnots:50,direction:0}}),/wind-flag/);
console.log('Combined station checks passed: sky cover, lowest BKN/OVC, calm/unknown wind, source-directed knot barbs and fixed nonoverlapping values.');
