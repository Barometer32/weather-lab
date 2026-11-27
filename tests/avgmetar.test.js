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
const mankatoLat = 44.2184;
const mankatoLon = -93.9179;
const localAirports = [
  ['KMKT', mankatoLat, mankatoLon, 30, 90],
  ['KNEAR', mankatoLat + .04, mankatoLon, 45, 90],
  ['KNEXT', mankatoLat + .09, mankatoLon, 60, 90],
  ['KFARTHER', mankatoLat + .12, mankatoLon, 90, 90],
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
const mankato = points.find(point => point.station === 'AVG-KMKT');

const nearly = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} ≈ ${expected}`);
const radians = Math.PI / 180;
assert.deepEqual(Array.from(points, point => point.name), ['Metro', 'Mankato'],
  'Only the metro and selected city airport have plots');
assert.deepEqual([mankato.lat, mankato.lon], [mankatoLat, mankatoLon]);
for (const source of metro.contributors) {
  nearly(source.miles, metro.contributors[0].miles);
  nearly(source.weight, 1 / 3);
}
nearly(metro.tempF, 49);
nearly(metro.dewpointF, 44);
nearly(metro.wind.meanSpeedMph, 10);
nearly(metro.wind.speedMph, 10 * (1 + 2 * Math.cos(10 * radians)) / 3);
nearly((metro.wind.direction + 1) % 360, 1);
assert.deepEqual(Array.from(mankato.contributors, source => source.station), ['KMKT', 'KNEAR', 'KNEXT']);
nearly(mankato.contributors[0].weight, .5);
const [,first,second] = mankato.contributors;
nearly(first.weight + second.weight, .5);
nearly(first.weight / second.weight, second.miles / first.miles);
nearly(mankato.tempF, 30 * .5 + 45 * first.weight + 60 * second.weight);
nearly(mankato.dewpointF, mankato.tempF - 5);
nearly(mankato.wind.direction, 90);
assert.ok(!model.estimates({...frame, stations: reports.filter(report => report.station !== 'KMKT')})
  .some(point => point.name === 'Mankato'), 'A city waits for its own airport report');
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
  const center = map.marker('Metro average');
  assert.ok(center);
  assert.equal(center.popup.children[0].textContent, 'Metro average');
  assert.ok(center.popup.children.some(line => line.textContent.startsWith('KMSP ·')));
  assert.match(center.icon.html, /data-mph="10"[^>]*rotate\(0\)/);
  assert.ok(center.popup.children.some(line => line.textContent.includes("9.9 mph from N (0°)")));
  assert.ok(center.popup.children.some(line => line.textContent.includes("10.0 mph from N (350°)")));
  map.frame(0);
  assert.match(map.marker('Metro average').popup.children[2].textContent, /49\.0°F/);
  const city = map.marker('Mankato average');
  assert.ok(city);
  assert.equal(city.popup.children[0].textContent, 'Mankato average');
  assert.ok(city.popup.children.some(line => line.textContent.startsWith('KMKT · 0.0 mi · 50%')));
  map.zoom(5);
  assert.ok(!map.marker('Mankato average') && map.marker('Metro average'));
  await map.mode('clouds');
  assert.ok(map.ids().every(id => !id.endsWith(' average')));
  await map.mode('avgmetar');
  assert.ok(map.marker('Metro average'));
  console.log('AVGMETAR passed: city anchors, equal metro mean, nearest-airport weighting, and hourly view switching.');
})().catch(error => { console.error(error); process.exitCode = 1; });
