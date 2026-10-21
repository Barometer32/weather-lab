'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const label={},events={};let interval;
const context={window:{},document:{getElementById:()=>label,addEventListener:(e,f)=>events[e]=f,hidden:false},Date,Math,setInterval:(f,ms)=>{interval=ms;}};
vm.runInNewContext(fs.readFileSync('static/sun-angle.js','utf8'),context);
const sun=context.window.WeatherSun.elevation;
assert.ok(sun(new Date('2026-06-21T18:15:00Z'))>68&&sun(new Date('2026-06-21T18:15:00Z'))<69);
assert.ok(sun(new Date('2026-12-21T18:15:00Z'))>21&&sun(new Date('2026-12-21T18:15:00Z'))<23);
assert.ok(sun(new Date('2026-10-19T06:00:00Z'))<0);
assert.ok(sun(new Date('2026-03-20T12:00:00Z'),0,0)>87);
assert.equal(sun(new Date('2026-10-19T14:00:00-05:00')),sun(new Date('2026-10-19T19:00:00Z')));
assert.ok(Number.isFinite(sun(new Date('2028-02-29T18:00:00Z'))));
assert.match(label.textContent,/^-?\d+\.\d°$/);
assert.equal(interval,10000);events.visibilitychange();
// Fixtures evaluated independently with NOAA's full published main.js calculator.
for(const [stamp,expected] of [
 ['2026-10-21T04:01:54Z',-47.6026392849484],
 ['2026-10-20T18:00:00Z',34.56426780479904],
 ['2026-06-21T18:00:00Z',68.28099749140354],
 ['2026-12-21T13:30:00Z',-3.5752816736953266]
])assert.ok(Math.abs(sun(new Date(stamp))-expected)<1e-8,stamp);
assert.equal(context.window.WeatherSun.latitude,44.925);
assert.equal(context.window.WeatherSun.longitude,-93.463);
// Correct a deliberately wrong device clock using the server timestamp.
context.window.WeatherSun.sync('2026-10-21T04:01:54Z');
assert.equal(label.textContent,'-47.6°');
console.log('Sun checks passed: NOAA reference values, Hopkins coordinates, seasons, refraction, time zones, server clock and 10-second refresh.');
