'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{},Math,Number};vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);
const m=context.window.WeatherStationModel;
const station={tempF:52,dewpointF:40,wind:{speedMph:7,direction:270},layers:[{cover:'BKN',baseFtAGL:2700}]};
const anchors=html=>[...html.matchAll(/class="(plot-temp|plot-dew|plot-speed)" x="([^"]+)" y="([^"]+)"/g)].map(v=>v.slice(1));
const example=m.vectorStationModel(station);
assert.match(example.html,/data-bearing-to="90"/,'A west wind points east');
assert.match(example.html,/plot-speed[^>]*>7</);assert.match(example.html,/class="station-dot"/);
assert.doesNotMatch(example.html,/wind-barb|wind-calm|plot-sky|plot-ceiling|NaN|undefined/);
for(let source=0;source<360;source+=5){
 const row={...station,wind:{speedMph:15,direction:source}},w=m.vectorWind(row.wind),f=m.vectorFootprint(row),plot=m.vectorStationModel(row);
 assert.equal(w.rotation,(source+180)%360);
 const tip=w.points[3],angle=source*Math.PI/180;
 assert.ok(Math.abs(tip[0]+14*Math.sin(angle))<1e-10);
 assert.ok(Math.abs(tip[1]-14*Math.cos(angle))<1e-10);
 for(const [x,y] of w.points){assert.ok(f.left<=(x-1.5)*m.scale&&f.right>=(x+1.5)*m.scale&&f.top<=(y-1.5)*m.scale&&f.bottom>=(y+1.5)*m.scale);}
 // Text ends/starts at +/-16; the full arrow envelope including halo clears it.
 assert.ok(w.points.every(([x])=>Math.abs(x)+.7<16));
 assert.deepEqual(anchors(plot.html),anchors(example.html));
 assert.equal(plot.anchor[0]/m.scale,52);assert.equal(plot.anchor[1]/m.scale,30);
}
for(const [wind,label] of [[{speedMph:0},'0'],[{speedMph:.2},'0'],[{speedMph:5.6,variable:true,direction:270},'VRB 6'],[{speedMph:5,direction:null},'? 5'],[null,'—']]){
 const html=m.vectorStationModel({...station,wind}).html;
 assert.doesNotMatch(html,/class="wind-vector"/);assert.ok(html.includes('>'+label+'</text>'));
}
assert.match(m.vectorStationModel({...station,wind:{speedKnots:10,direction:0}}).html,/plot-speed[^>]*>12</,'Speed is displayed in mph, not knots');
const short=m.vectorFootprint(station),long=m.vectorFootprint({...station,tempF:-120,dewpointF:-130,wind:{speedMph:120,direction:270}});
assert.ok(long.left<short.left&&long.right>short.right,'Footprints reserve longer numeric labels');
console.log('Vector plots passed: all bearings point TO the wind destination, whole mph, calm/VRB/unknown cases, exact station anchors, fixed labels and collision bounds.');
