'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),node=()=>({children:[],hidden:false,textContent:'',append(...v){this.children.push(...v);},replaceChildren(){this.children=[];}});
const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
const source=fs.readFileSync('static/app.js','utf8'),begin=source.indexOf('let forecastBusy'),end=source.indexOf('async function loadForecast',begin);
const now=Date.parse('2026-11-17T18:00:00Z');class ClockDate extends Date{static now(){return now;}}
const c={$:get,document:{createElement:node},Date:ClockDate,fullTime:new Intl.DateTimeFormat('en-US',{timeZone:'America/Chicago',dateStyle:'medium',timeStyle:'short'})};
vm.createContext(c);vm.runInContext(source.slice(begin,end)+'\nglobalThis.draw=d=>{forecastData=d;renderForecast();};',c);
const start='2026-11-17T18:00:00Z',stop='2026-11-18T00:00:00Z';
const period={name:'Saturday',startTime:start,endTime:stop,isDaytime:true,temperature:47,temperatureUnit:'F',temperatureTrend:'falling',trendTargetTime:'5pm',detailedForecast:'Rain likely. Temperature falling to around 47 by 5pm.',hourlyWindows:[{condition:'Old detail'}],precipAmounts:[{inches:1}]};
c.draw({updatedAt:start,periods:[period]});
const row=get('forecast-periods').children[0],heading=row.children[0],temp=heading.children[1];
assert.equal(temp.children[0].textContent,'Falling');assert.equal(temp.children[1].textContent,'↓47°F');assert.match(temp.title,/by 5pm/);
assert.equal(row.children[1].textContent,period.detailedForecast);assert.equal(row.children.length,2,'text forecast has no extra detail or amount lists');
assert.match(get('forecast-updated').textContent,/^NWS updated .* · Central time$/);
c.draw({periods:[{...period,temperatureTrend:null}]});assert.equal(get('forecast-periods').children[0].children[0].children[1].children[0].textContent,'High');
console.log('Forecast display passed: NWS update time, text narrative, and temperature targets.');
