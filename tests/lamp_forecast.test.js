'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const node = () => ({children: [], textContent: '', append(...children) {
  this.children.push(...children);
}, replaceChildren() { this.children = []; }});
const root = node();
const context = {Intl, Date, window: {}, document: {createElement: node, getElementById: () => root}};
vm.runInNewContext(fs.readFileSync('static/lamp-forecast.js','utf8'), context);
const render = context.window.WeatherLampForecast.render;
const future = {startTime: '2026-11-20T08:00:00Z', endTime: '2026-11-20T09:00:00Z',
  temperatureF: 50, dewpointF: 30, windMph: 7.2, windDirection: 350, skyCover: 'Broken',
  ceiling: '2,000–3,000 ft AGL', precipChancePct: 60};
const expired = {...future, startTime: '2026-11-20T07:00:00Z', endTime: future.startTime};
render({hours: [expired, future]}, Date.parse(future.startTime));
const list = root.children[1];
assert.equal(list.children.length, 2);
const row = list.children[1];
assert.equal(row.children[0].children[1].textContent, '2:00 AM–3:00 AM');
assert.deepEqual(row.children.slice(1).map(cell => cell.children[1].textContent),
  ['50°F', '30°F', 'N 7 mph', 'Broken', '2,000–3,000 ft AGL', '60%']);
render(undefined, Date.parse(future.startTime));
assert.match(root.children[0].textContent, /unavailable/);
console.log('LAMP view passed: hourly interval, all six values, expired rows and empty state.');
