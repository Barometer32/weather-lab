'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{},Math,Number};vm.runInNewContext(fs.readFileSync('static/metar-model.js','utf8'),context);
const m=context.window.WeatherStationModel;
const station={tempF:71,dewpointF:50,wind:{speedMph:17.261685,speedKnots:15,direction:270},skyCover:{code:'BKN'},layers:[{cover:'SCT',baseFtAGL:1000},{cover:'OVC',baseFtAGL:10000},{cover:'BKN',baseFtAGL:2700}]};
const plot=m.combinedStationModel(station);
assert.match(plot.html,/class="plot-temp" x="32.5" y="31" text-anchor="end">71/);
assert.match(plot.html,/class="plot-dew" x="32.5" y="50" text-anchor="end">50/);
assert.match(plot.html,/class="plot-ceiling" x="48" y="40" text-anchor="start">3/);
assert.doesNotMatch(plot.html,/plot-speed/,'Wind is encoded only by the barb on the map');
assert.match(plot.html,/rotate\(270\) scale\(1\.1448\)/);
assert.match(plot.html,/class="wind-shaft"[^>]*stroke-width="1.7"/);
assert.match(plot.html,/wind-barb" data-knots="15".*rotate\(270\)/);
assert.ok(plot.html.indexOf('class="wind-barb"')<plot.html.indexOf('class="plot-temp"'),'The wind barb draws behind temperature text');
assert.ok(plot.html.indexOf('class="wind-barb"')<plot.html.indexOf('class="plot-dew"'),'The wind barb draws behind dewpoint text');
assert.match(plot.html,/class="sky-fill"/);assert.doesNotMatch(plot.html,/wind-vector/);
assert.equal(plot.anchor[0]/m.scale,40);assert.equal(plot.anchor[1]/m.scale,36);
const anchors=html=>[...html.matchAll(/class="(plot-temp|plot-dew|plot-speed|plot-ceiling)" x="([^"]+)" y="([^"]+)"/g)].map(match=>match.slice(1));
for(const [knots,flags,full,half] of [[5,0,0,true],[10,0,1,false],[15,0,1,true],[45,0,4,true],[50,1,0,false],[55,1,0,true],[65,1,1,true],[100,2,0,false],[145,2,4,true]]){
 for(let direction=0;direction<360;direction+=5){
  const row={...station,tempF:-12,dewpointF:-21,wind:{speedMph:knots*1.150779,speedKnots:knots,direction}},w=m.combinedWind(row.wind),bounds=m.combinedFootprint(row),html=m.combinedStationModel(row).html;
  assert.equal(w.rotation,direction);assert.equal(w.roundedKnots,knots);
  assert.equal(w.pennants.length,flags);assert.equal(w.lines.length,1+full+(half?1:0));
  for(const [x,y] of w.points){assert.ok(bounds.left<=x*m.scale-1.5*m.scale);assert.ok(bounds.right>=x*m.scale+1.5*m.scale);assert.ok(bounds.top<=y*m.scale-1.5*m.scale);assert.ok(bounds.bottom>=y*m.scale+1.5*m.scale);}
  assert.deepEqual(anchors(html),anchors(plot.html),'Bearing and number length never shift text anchors');
  assert.doesNotMatch(html,/NaN|undefined|plot-speed/);
 }
}
assert.equal(m.combinedWind({speedMph:11.50779,direction:90}).roundedKnots,10,'Feathers use knots, not the mph text');
for(const [knots,rounded] of [[2,0],[3,5],[7,5],[8,10],[12,10],[13,15]]){
 const w=m.combinedWind({speedKnots:knots,direction:0});assert.equal(w.roundedKnots,rounded);
}
for(const [speedMph,rounded,feathers] of [[3,5,[4.75]],[7.9,5,[4.75]],[8,10,[9.5]],
 [12.9,10,[9.5]],[13,15,[9.5,4.75]],[15,15,[9.5,4.75]],[18,20,[9.5,9.5]]]){
 const w=m.combinedWind({speedMph,direction:270},true);
 assert.equal(w.roundedMph,rounded);
 assert.equal(w.rotation,270);
 assert.deepEqual(Array.from(w.lines.slice(1),line=>line[1][0]),feathers);
}
for(const speedMph of [0,1,2,2.9]){
 const row={...station,wind:{speedMph,direction:270}};
 assert.equal(m.combinedWind(row.wind,true).kind,'calm');
 const html=m.combinedStationModel(row,{dot:true,mphBarbs:true}).html;
 assert.match(html,/mesonet-dot/);
 assert.doesNotMatch(html,/wind-barb|wind-shaft|wind-calm/);
}
const calm=m.combinedStationModel({...station,wind:{speedMph:0,speedKnots:0}}).html;
assert.match(calm,/wind-calm/);assert.doesNotMatch(calm,/plot-speed|Calm|calm<|wind-barb"/);
const short=m.combinedWind({speedKnots:5,direction:0}),full=m.combinedWind({speedKnots:10,direction:0}),double=m.combinedWind({speedKnots:20,direction:0});
assert.equal(short.lines[1][1][0],4.75);assert.equal(full.lines[1][1][0],9.5);
assert.ok(Math.abs(double.lines[2][0][1]-double.lines[1][0][1]-4.7025)<1e-9,'Separate feathers remain distinguishable at map scale');
assert.ok(Math.abs(full.lines[0][1][1]/(-28*.9405)-1.05)<1e-12,'Barb staff is 5% longer than the previous setting; feather width and stroke remain unchanged');
const vrb=m.combinedStationModel({...station,wind:{speedMph:7,direction:null,variable:true}}).html;
assert.match(vrb,/>VRB<\/text>/);assert.doesNotMatch(vrb,/wind-barb"/);
assert.doesNotThrow(()=>m.combinedStationModel({...station,wind:null}));
for(const code of ['CLR','FEW','SCT']){
 const html=m.combinedStationModel({...station,skyCover:{code},layers:[{cover:code,baseFtAGL:2700}]}).html;
 assert.match(html,/plot-sky/);assert.doesNotMatch(html,/plot-ceiling/);
}
assert.match(m.combinedStationModel({...station,skyCover:{code:'BKN'},layers:[{cover:'BKN',baseFtAGL:null}]}).html,/plot-ceiling[^>]*>\?/);
for(const [baseFtAGL,label] of [[1000,'1'],[12000,'12'],[25000,'25']]){
 assert.match(m.combinedStationModel({...station,layers:[{cover:'BKN',baseFtAGL}]}).html,new RegExp('plot-ceiling[^>]*>'+label+'<'));
}
console.log('Combined station model passed: fixed compact quadrants, cloud coverage/ceiling, standard 5/10/50-kt feathers, calm/VRB and rotated collision extents.');

// Dot mode removes all cloud encoding, including a calm-wind ring, for both feeds.
for(const wind of [{speedKnots:10,direction:270},{speedMph:0}]){
 const dot=m.combinedStationModel({...station,wind},{dot:true}).html;
 assert.match(dot,/class="mesonet-dot"/);assert.doesNotMatch(dot,/plot-sky|sky-fill|plot-ceiling|wind-calm/);
 if(wind.direction)assert.match(dot,/class="wind-shaft" d="M0 0L0 -27\.6507/,'The shaft starts at the exact station dot');
}

// The denser collision geometry must still contain every painted barb segment,
// including the shaft extended down to the dot and the pennant halos.
for(const speedMph of [3,7,10,15,45,50,55,100,145])for(let direction=0;direction<360;direction+=5){
 const row={...station,tempF:-12,dewpointF:-21,wind:{speedMph,direction}},w=m.combinedWind(row.wind,true);
 const boxes=m.combinedCollisionBoxes(row,{dot:true,mphBarbs:true}),a=direction*Math.PI/180;
 const transform=([x,y])=>[(x*Math.cos(a)-y*Math.sin(a))*1.1448*m.scale,(x*Math.sin(a)+y*Math.cos(a))*1.1448*m.scale];
 const contains=([x,y])=>boxes.some(b=>x>=b.left-1e-8&&x<=b.right+1e-8&&y>=b.top-1e-8&&y<=b.bottom+1e-8);
 const lines=[[[0,0],w.lines[0][1]],...w.lines.slice(1)];
 for(const [start,end] of lines)for(let i=0;i<=20;i++){
  const p=transform([start[0]+(end[0]-start[0])*i/20,start[1]+(end[1]-start[1])*i/20]);
  for(const angle of [0,Math.PI/2,Math.PI,Math.PI*1.5])assert.ok(contains([p[0]+1.65*1.1448*m.scale*Math.cos(angle),p[1]+1.65*1.1448*m.scale*Math.sin(angle)]),'a shaft/feather halo must be reserved');
 }
 for(const polygon of w.pennants)for(const p of polygon.map(transform))assert.ok(contains(p),'flags remain protected');
}
console.log('Dense collision geometry contains barbs and halos at every tested bearing and speed.');

for(const wind of [{speedMph:10,direction:60},{speedMph:5,direction:null,variable:true}]){
 const row={...station,wind},before=JSON.stringify(row);
 const shown=m.combinedStationModel(row,{dot:true,mphBarbs:true}),hidden=m.combinedStationModel(row,{dot:true,mphBarbs:true,hideBarb:true});
 assert.deepEqual(anchors(hidden.html),anchors(shown.html),'hiding a conflicting wind symbol cannot move any numbers');
 assert.doesNotMatch(hidden.html,/class="wind-barb"|plot-wind-state/);
 assert.match(hidden.html,/mesonet-dot/);
 assert.equal(JSON.stringify(row),before,'suppressing a symbol cannot change the actual wind report');
}
