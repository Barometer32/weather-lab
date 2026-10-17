'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const SunCalc=require('../static/vendor/suncalc.js');
let clock=Date.parse('2026-06-21T18:00:00Z');
class ClockDate extends Date{constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;}}
const card={dataset:{lat:'44.9244',lon:'-93.4140',location:'Hopkins, MN'}};
const value={textContent:''},detail={textContent:''},panel={hidden:true};
const nodes={'sun-angle':card,'sun-angle-value':value,'sun-angle-detail':detail,satellite:panel};
const events={},timers=[],calls=[];
const document={hidden:false,getElementById:id=>nodes[id],addEventListener:(name,fn)=>{events[name]=fn;}};
const window={SunCalc:{getPosition(date,lat,lon){calls.push({date,lat,lon});return SunCalc.getPosition(date,lat,lon);}}};
const context={window,document,Intl,Date:ClockDate,Number,Math,setInterval(fn,ms){timers.push({fn,ms});},fetch(){throw Error('Sun angle must not request data');}};
vm.runInNewContext(fs.readFileSync('static/sun-angle.js','utf8'),context);
// Known seasonal geometry: near local noon, Hopkins reaches about 68° in June.
assert.ok(parseFloat(value.textContent)>65&&parseFloat(value.textContent)<70,value.textContent);
assert.equal(calls[0].lat,44.9244);assert.equal(calls[0].lon,-93.4140);
assert.match(detail.textContent,/Above the horizon.*Hopkins, MN.*1:00 PM CDT/);
const timer=timers.find(t=>t.ms===60000);assert.ok(timer);
clock=Date.parse('2026-06-22T06:00:00Z');const before=value.textContent;
timer.fn();assert.equal(value.textContent,before); // Hidden Satellite does no periodic work.
panel.hidden=false;window.WeatherSun.refresh();
assert.ok(parseFloat(value.textContent)<0);assert.match(detail.textContent,/Below the horizon.*1:00 AM CDT/);
assert.equal(card.dataset.position,'below');
document.hidden=true;clock=Date.parse('2026-12-21T18:00:00Z');const night=value.textContent;
timer.fn();assert.equal(value.textContent,night);
document.hidden=false;events.visibilitychange();
assert.ok(parseFloat(value.textContent)>18&&parseFloat(value.textContent)<24,value.textContent);
assert.match(detail.textContent,/12:00 PM CST/);
window.SunCalc={getPosition:()=>({altitude:0})};window.WeatherSun.refresh();
assert.equal(value.textContent,'0.0°');assert.match(detail.textContent,/At the horizon/);
window.SunCalc=undefined;window.WeatherSun.refresh();
assert.equal(value.textContent,'—');assert.match(detail.textContent,/unavailable/);
console.log('Sun-angle checks passed: seasonal geometry, Hopkins coordinates, night/horizon, Central DST, visibility refresh, missing library, and no API requests.');
