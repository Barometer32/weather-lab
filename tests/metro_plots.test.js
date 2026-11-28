'use strict';
const assert = require('node:assert/strict');
const viewer = require('./metro_viewer');

const airports = [
  ['KMSP', 44.8852, -93.2313, 30, 350],
  ['KFCM', 44.8321, -93.4705, 36, 0],
  ['KMIC', 45.0623, -93.3511, 33, 10],
  ['KMKT', 44.2184, -93.9179, 40, 90],
  ['KRWF', 44.5483, -95.0804, 39, 180],
  ['KSTC', 45.5442, -94.0516, 35, 180],
  ['KRST', 43.904, -92.4921, 41, 180],
  ['KDLH', 46.8435, -92.1866, 27, 180],
  ['KAEL', 43.6823, -93.3722, 38, 180],
  ['KAXN', 45.8680, -95.3940, 26, 180],
  ['KBRD', 46.4021, -94.1273, 29, 180],
  ['KHCD', 44.8597, -94.3855, 32, 180],
  ['KJMR', 45.8885, -93.2690, 28, 180],
  ['KRGK', 44.5926, -92.4844, 34, 180],
  ['KBDH', 45.1111, -95.1258, 37, 180],
  ['KSTP', 44.9345, -93.0600, 31, 180],
  ['KANE', 45.145, -93.211, 42, 140],
];
const history = Array.from({length: 4}, (_, hour) => ({
  hour: new Date(Date.UTC(2026, 10, 17, 15 + hour)).toISOString(),
  stations: airports.map(([station, lat, lon, temperature, direction]) => ({
    station, lat, lon,
    reportType: 'METAR',
    time: new Date(Date.UTC(2026, 10, 17, 14 + hour, 53)).toISOString(),
    tempF: temperature + hour,
    dewpointF: temperature - 15 + hour,
    wind: {speedMph: 10, direction},
    layers: [{cover: 'BKN', baseFtAGL: 2000}],
  })),
}));
history[1].stations = history[1].stations.filter(report => report.station !== 'KMIC');
history[2].stations = history[2].stations.map(report => report.station === 'KDLH'
  ? {...report, reportType: 'SPECI'} : report);

(async () => {
  const data = {checkedAt: '2026-11-17T18:02:00Z', history};
  const map = viewer(data, {width: 1800, height: 850, zoom: 10, center: [44.98, -93.34]});
  await map.load();
  assert.equal(map.get('metar-title').textContent, 'METAR');
  for (let hour = 0; hour < 4; hour++) {
    map.frame(hour);
    assert.ok(!map.ids().includes('AVG-METRO') && !map.ids().includes('METRO'));
    for (const [id, lat, lon, temperature] of airports.filter(([station]) => ['KMSP', 'KFCM', 'KMIC', 'KSTP', 'KANE'].includes(station))) {
      const plot = map.marker(id);
      if (id === 'KMIC' && hour === 1) {
        assert.equal(plot, undefined);
        continue;
      }
      assert.ok(plot, id + ' is plotted at its own station');
      assert.deepEqual(Array.from(plot.position), [lat, lon]);
      assert.equal(plot.popup.children[2].textContent, 'Temperature: ' + (temperature + hour) + '.0°F');
      assert.match(plot.icon.html, /plot-temp/);
    }
  }

  const duluth = viewer(data, {width: 800, height: 500, zoom: 10, center: [46.84, -92.19]});
  await duluth.load();
  assert.ok(duluth.marker('KDLH'));
  duluth.frame(2);
  assert.equal(duluth.marker('KDLH'), undefined, 'Special reports are excluded from the routine loop');
  await map.mode('clouds');
  assert.equal(map.get('metar-title').textContent, 'CLOUDS');
  assert.match(map.marker('KMSP').icon.html, /plot-sky/);
  await map.mode('metar');
  assert.match(map.marker('KMSP').icon.html, /plot-temp/);
  assert.ok(map.reads.every(url => url === '/api/station-plots?view=loop'));
  console.log('METAR plots individual airport reports, including airports outside the old city list.');
})().catch(error => { console.error(error); process.exitCode = 1; });
