'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const viewer = require('./metro_viewer');

const sandbox = {window: {}};
vm.runInNewContext(fs.readFileSync('static/avgmetar.js', 'utf8'), sandbox);
const model = sandbox.window.WeatherAvgMetar;
const airports = [
  ['KMSP', 44.8852, -93.2313, 53, 350],
  ['KFCM', 44.8321, -93.4705, 44, 0],
  ['KMIC', 45.0623, -93.3511, 50, 10],
];
const [eastLat, eastLon] = model.nextEast;
const localAirports = [
  ['KE01', eastLat, eastLon, 30, 90],
  ['KE02', eastLat + .04, eastLon, 45, 90],
  ['KE03', eastLat + .09, eastLon, 60, 90],
  ['KE04', eastLat + .12, eastLon, 90, 90],
  ['KSTP', eastLat, eastLon, 99, 90],
];
const reports = [...airports, ...localAirports].map(([station, lat, lon, tempF, direction]) => ({
  station, lat, lon, tempF, dewpointF: tempF - 5, reportType: 'METAR', wind: {speedMph: 10, direction},
}));
reports.push({...reports[3], station: 'KSPECI', reportType: 'SPECI'});
const history = Array.from({length: 4}, (_, i) => ({
  hour: new Date(Date.UTC(2026, 10, 26, 14 + i)).toISOString(),
  stations: reports.map(report => ({...report, tempF: report.tempF + i})),
}));
const frame = history[0];
const points = model.estimates(frame);
const metro = points.find(point => point.metro);
const east = points.find(point => point.east === 1 && point.north === 0);
const north = points.find(point => point.north === 1 && point.east === 0);

const nearly = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} ≈ ${expected}`);
const radians = Math.PI / 180;
function distance(a, b) {
  const angle = Math.sin((a.lat - b.lat) * radians / 2) ** 2
    + Math.cos(a.lat * radians) * Math.cos(b.lat * radians) * Math.sin((a.lon - b.lon) * radians / 2) ** 2;
  return 2 * 3958.76 * Math.asin(Math.sqrt(angle));
}
nearly(distance(metro, east), 25);
nearly(distance(metro, north), 25);
for (const source of metro.contributors) {
  nearly(source.miles, metro.contributors[0].miles);
  nearly(source.weight, 1 / 3);
}
nearly(metro.tempF, 49);
nearly(metro.dewpointF, 44);
nearly(metro.wind.meanSpeedMph, 10);
nearly(metro.wind.speedMph, 10 * (1 + 2 * Math.cos(10 * radians)) / 3);
nearly((metro.wind.direction + 1) % 360, 1);
assert.deepEqual(Array.from(east.contributors, source => source.station), ['KE01', 'KSTP', 'KE02']);
nearly(east.contributors[0].weight, east.contributors[1].weight);
assert.ok(east.contributors[1].weight > east.contributors[2].weight);
const total = east.contributors.reduce((sum, source) => sum + 1 / Math.max(1, source.miles), 0);
nearly(east.tempF, (30 + 99 + 45 / east.contributors[2].miles) / total);
assert.equal(model.estimates(frame), points, 'Changing zoom can reuse an hourly calculation');
const later = model.estimates(history[1]).find(point => point.metro);
assert.deepEqual([later.lat, later.lon], [metro.lat, metro.lon]);
nearly(later.tempF, 50);
assert.ok(!model.estimates({...frame, stations: reports.filter(report => report.station !== 'KMIC')}).some(point => point.metro));
assert.equal(model.estimates({...frame, stations: reports.slice(0, 2)}).length, 0);
const missingDew = model.estimates({...frame, stations: reports.map(report => report.station === 'KMIC'
  ? {...report, dewpointF: null} : report)}).find(point => point.metro);
assert.equal(missingDew.dewpointF, null);
const metroWind = winds => model.estimates({...frame, stations: reports.map((report, i) =>
  i < 3 ? {...report, wind: winds[i]} : report)}).find(point => point.metro).wind;
const eastWest = metroWind([{speedMph: 12, direction: 90}, {speedMph: 12, direction: 270}, {speedMph: 0}]);
nearly(eastWest.meanSpeedMph, 8);
assert.equal(eastWest.speedMph, 0);
assert.equal(eastWest.direction, null);
const eastResult = metroWind([{speedKnots: 10, speedMph: 11.5, direction: 90},
  {speedMph: 5, direction: 270}, {speedMph: 12, variable: true}]);
nearly(eastResult.speedMph, (11.50779 - 5) / 2);
nearly(eastResult.direction, 90);
assert.equal(eastResult.vectorCount, 2);
const variable = metroWind(Array.from({length: 3}, () => ({speedMph: 7, variable: true})));
nearly(variable.speedMph, 7);
assert.equal(variable.direction, null);
assert.equal(variable.variable, true);

(async () => {
  const map = viewer({history}, {width: 1200, height: 800, zoom: 8});
  await map.load();
  assert.equal(map.get('metar-product').value, 'avgmetar');
  const center = map.marker('AVG-METRO');
  assert.ok(center);
  assert.equal(center.popup.children[0].textContent, 'Metro average');
  assert.ok(center.popup.children.some(line => line.textContent.startsWith('KMSP ·')));
  assert.match(center.icon.html, /data-mph="10"[^>]*rotate\(0\)/);
  assert.ok(center.popup.children.some(line => line.textContent.includes("9.9 mph from N (0°)")));
  assert.ok(center.popup.children.some(line => line.textContent.includes("10.0 mph from N (350°)")));
  map.frame(0);
  assert.match(map.marker('AVG-METRO').popup.children[2].textContent, /49\.0°F/);
  assert.ok(map.ids().includes('AVG-1,0'));
  map.zoom(6);
  assert.ok(!map.ids().includes('AVG-1,0') && map.ids().includes('AVG-METRO'));
  await map.mode('plots');
  assert.ok(map.ids().every(id => !id.startsWith('AVG-')));
  assert.ok(!map.ids().includes('KMSP'));
  await map.mode('avgmetar');
  assert.ok(map.ids().includes('AVG-METRO'));
  console.log('AVGMETAR passed: fixed 25-mile grid, equal metro mean, nearest-station weighting, and hourly view switching.');
})().catch(error => { console.error(error); process.exitCode = 1; });
