'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),node=()=>({children:[],textContent:'',append(...v){this.children.push(...v);},replaceChildren(){this.children=[];}});
const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
const source=fs.readFileSync('static/app.js','utf8'),begin=source.indexOf('let forecastBusy'),end=source.indexOf('async function loadForecast',begin);
const now=Date.parse('2026-11-17T18:00:00Z');class ClockDate extends Date{static now(){return now;}}
const c={$:get,document:{createElement:node},Intl,Date:ClockDate,Number,Set,fullTime:new Intl.DateTimeFormat('en-US',{timeZone:'America/Chicago',dateStyle:'medium',timeStyle:'short'})};
vm.createContext(c);vm.runInContext(source.slice(begin,end)+'\nglobalThis.draw=d=>{forecastData=d;renderForecast();};',c);
const start='2026-11-17T18:00:00Z',stop='2026-11-18T00:00:00Z';
const period={name:'Saturday',startTime:start,endTime:stop,isDaytime:true,temperature:47,temperatureUnit:'F',temperatureTrend:'falling',trendTargetTime:'5pm',detailedForecast:'Rain likely. Temperature falling to around 47 by 5pm.',
 hourlyWindows:[{startTime:start,endTime:'2026-11-17T20:00:00Z',condition:'Cloudy',minCloudPct:90,maxCloudPct:100,minChancePct:60,maxChancePct:70,weather:['Rain likely (light)']},
 {startTime:'2026-11-17T20:00:00Z',endTime:stop,condition:'Partly cloudy',minCloudPct:40,maxCloudPct:55,minChancePct:null,maxChancePct:null,weather:[]}],
 precipAmounts:[{startTime:start,endTime:stop,kind:'Liquid precipitation',inches:.1}]};
const data={updatedAt:start,hourlyUpdatedAt:start,periods:[period]};c.draw(data);
const row=get('forecast-periods').children[0],heading=row.children[0],copy=row.children[1],temp=heading.children[1];
assert.equal(temp.children[0].textContent,'Falling');assert.equal(temp.children[1].textContent,'↓47°F');assert.match(temp.title,/by 5pm/);
assert.equal(copy.children[0].textContent,period.detailedForecast);
const details=copy.children[2].children.map(n=>n.textContent);
assert.match(details[0],/12:00 PM–2:00 PM: Cloudy \(90–100% cloud cover\).*Rain likely \(light\).*60–70%/);
assert.match(details[1],/2:00 PM–6:00 PM: Partly cloudy \(40–55% cloud cover\)/);assert.doesNotMatch(details[1],/Precipitation chance/);
assert.match(details[2],/Liquid precipitation 0.10 in total/);
assert.match(get('forecast-updated').textContent,/Hourly detail updated/);
c.draw({periods:[{...period,temperatureTrend:null,hourlyWindows:[],precipAmounts:[]}]});
assert.equal(get('forecast-periods').children[0].children[0].children[1].children[0].textContent,'High');
assert.equal(get('forecast-periods').children[0].children[1].children.length,1,'narrative remains usable when detail is unavailable');
console.log('Forecast display passed: falling target, original narrative, timed cloud/precip percentages, totals, and missing-detail fallback.');
