'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{},Math,Number};
vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);
const model=context.window.WeatherStationModel;
const station={tempF:46,dewpointF:41,wind:{speedMph:20,direction:90},skyCover:{code:'BKN',displayFraction:.75,oktaRange:[5,7],description:'Broken clouds'},ceiling:{baseFtAGL:2700,cover:'BKN',kind:'ceiling'}};
const svg=model.stationModel(station);
assert.match(svg,/class="plot-sky" data-cover="BKN"/);
assert.match(svg,/M0 -8.5V-14/); // Arrow begins outside the 5.5-unit cloud circle.
assert.match(svg,/rotate\(270\)/); // Easterly wind flows west.
assert.match(svg,/>46<\/text>/);assert.match(svg,/>41<\/text>/);assert.match(svg,/>20<\/text>/);
assert.match(svg,/class="plot-ceiling"[^>]*>27<\/text>/);
assert.match(model.cloudText(station),/5–7\/8/);
assert.match(model.cloudText(station),/2,700 ft AGL/);
for(const [code,fill] of [['CLR',0],['FEW',.25],['SCT',.5],['BKN',.75],['OVC',1]]){
 const result=model.stationModel({...station,skyCover:{code,displayFraction:fill}});
 assert.ok(result.includes(`data-cover="${code}"`));
 assert.equal(result.includes('class="plot-sky-unknown"'),false);
 if(fill>0&&fill<1)assert.match(result,/<path d="M34 24 L34 18.5 A5.5 5.5/);
}
assert.match(model.stationModel({...station,skyCover:{code:'VV'}}),/M31 21L37 27/);
assert.match(model.stationModel({...station,skyCover:{code:null}}),/class="plot-sky-unknown"/);
assert.equal(model.ceilingText({...station,ceiling:null}),'');
assert.equal(model.ceilingText({...station,ceiling:{baseFtAGL:300}}),'03');
assert.equal(model.ceilingText({...station,ceiling:{baseFtAGL:12000}}),'120');
assert.equal(model.ceilingText({...station,ceiling:{baseFtAGL:null}}),'?');
assert.equal(model.ceilingText({...station,ceiling:{baseFtAGL:300,kind:'verticalVisibility'}}),'VV 03');
assert.match(model.stationModel({...station,wind:{speedMph:0}}),/class="calm-ring"/);
assert.ok(!model.stationModel({...station,wind:{speedMph:0}}).includes('class="wind-arrow"'));
assert.match(model.stationModel({...station,wind:{speedMph:10,direction:null,variable:true}}),/>VRB<\/text>/);
assert.match(svg,/class="plot-temp" x="\d+" y="16"/);
assert.match(svg,/class="plot-dew" x="\d+" y="37"/);
assert.match(svg,/class="plot-ceiling" x="55" y="16"/);
assert.match(svg,/class="plot-speed" x="55" y="37"/);
assert.equal(model.iconSize[1],44*.82);
assert.ok(model.footprint(station).right>=model.footprint({...station,ceiling:null}).right);
const labelAnchors=html=>[...html.matchAll(/class="(plot-temp|plot-dew|plot-ceiling|plot-speed)" x="([^"]+)" y="([^"]+)"/g)].map(m=>m.slice(1)).sort();
const fixed=labelAnchors(svg);
for(const speedMph of [null,0,10])assert.deepEqual(labelAnchors(model.stationModel({...station,wind:{speedMph}})),fixed);
for(let direction=0;direction<360;direction+=5){
 const result=model.stationModel({...station,wind:{speedMph:20,direction}});
 assert.ok(result.includes(`rotate(${(direction+180)%360})`));
 assert.deepEqual(labelAnchors(result),fixed,`labels remain fixed for wind from ${direction}`);
 // All rotated arrow points, including each path’s actual white halo,
 // remain between the nearest text edges (13+1.5 and 55-1.5).
 const a=(direction+180)*Math.PI/180;
 for(const [x,y,halo] of [[0,-8.5,2.5],[0,-14,2.5],[0,-18,.8],[-3.2,-12.8,.8],[3.2,-12.8,.8]]){
  const arrowX=34+x*Math.cos(a)-y*Math.sin(a);
  assert.ok(arrowX-halo>14.5&&arrowX+halo<53.5,`arrow clears text at ${direction}`);
 }
}
console.log('Combined station-model checks passed: category fills, separated arrow, ceilings, all wind headings, calm, variable and unknown states.');

