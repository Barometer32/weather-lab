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
  ['KFCY', 45.1, -93.1, 57, 90],
  ['KFAR', 46.9207, -96.8157, 48, 180],
  ['KFSD', 43.582, -96.7419, 46, 180],
  ['KDSM', 41.5339, -93.6631, 45, 180],
  ['KMKE', 42.9472, -87.8966, 43, 180],
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

const getReport = (frame, station) => history[frame].stations.find(report => report.station === station);
getReport(3, 'KMSP').wind = {speedMph: 12, direction: 350};
getReport(3, 'KFCM').wind = {speedMph: 24, variable: true};
getReport(3, 'KMIC').wind = {speedMph: 12, direction: 10};
for (const station of ['KMSP', 'KFCM', 'KMIC']) getReport(2, station).wind = {speedMph: 2};

(async () => {
  const data = {checkedAt: '2026-11-17T18:02:00Z', history};
  const map = viewer(data, {width: 1800, height: 850, zoom: 9});
  await map.load();
  assert.equal(map.get('metar-title').textContent, 'METAR');

  const distance = ([lat, lon], [a, b]) => {
    const rad = Math.PI / 180;
    return Math.acos(Math.sin(lat * rad) * Math.sin(a * rad)
      + Math.cos(lat * rad) * Math.cos(a * rad) * Math.cos((lon - b) * rad));
  };
  for (let hour = 0; hour < 4; hour++) {
    map.frame(hour);
    const metro = map.marker('METRO');
    for (const id of ['KMSP', 'KFCM', 'KMIC', 'KSTP', 'KANE', 'KFCY', 'KHCD', 'KRGK']) {
      assert.equal(map.marker(id), undefined, id + ' must stay out of METAR plots');
    }
    if (hour === 1) {
      assert.equal(metro, undefined, 'One missing airport prevents that hour’s metro average');
      continue;
    }
    assert.ok(metro);
    const distances = airports.slice(0, 3).map(([, lat, lon]) => distance(metro.position, [lat, lon]));
    assert.ok(Math.max(...distances) - Math.min(...distances) < 1e-8, 'The average is equidistant from all three airports');
    assert.equal(metro.popup.children[0].textContent, 'Twin Cities average (KMSP · KFCM · KMIC)');
    assert.equal(metro.popup.children[2].textContent, 'Temperature: ' + (33 + hour) + '.0°F');
    assert.equal(metro.popup.children[3].textContent, 'Dewpoint: ' + (18 + hour) + '.0°F');
    assert.match(metro.icon.html, /plot-temp/);
    assert.doesNotMatch(metro.icon.html, /wind-vector|plot-speed/);
    if (hour === 0) assert.match(metro.icon.html, /class="wind-barb" data-mph="10"/);
    if (hour === 2) assert.doesNotMatch(metro.icon.html, /wind-barb/, 'Calm winds have no barb');
    if (hour === 3) assert.equal(metro.popup.children[4].textContent, 'Wind: 16 mph from 0°',
      'Variable reports contribute speed while the other stations determine direction');
  }

  for (const id of ['KMKT', 'KSTC', 'KRWF', 'KDLH', 'KFAR', 'KFSD', 'KDSM', 'KMKE']) {
    const [, lat, lon, temperature] = airports.find(([station]) => station === id);
    const city = viewer(data, {width: 800, height: 500, zoom: 9, center: [lat, lon]});
    await city.load();
    const plot = city.marker(id);
    assert.ok(plot, id + ' appears at its own airport');
    assert.deepEqual(Array.from(plot.position), [lat, lon]);
    assert.equal(plot.popup.children[2].textContent, 'Temperature: ' + (temperature + 3) + '.0°F');
    if (id === 'KDLH') {
      city.frame(2);
      assert.equal(city.marker(id), undefined, 'Special reports are excluded from the routine loop');
    }
  }
  await map.mode('clouds');
  assert.equal(map.get('metar-title').textContent, 'CLOUDS');
  assert.match(map.marker('KMSP').icon.html, /plot-sky/);
  assert.equal(map.marker('METRO'), undefined);
  await map.mode('metar');
  assert.match(map.marker('METRO').icon.html, /plot-temp/);
  assert.ok(map.reads.every(url => url === '/api/station-plots?view=loop'));
  console.log('METAR shows one equidistant metro average and selected airports in all five states.');
})().catch(error => { console.error(error); process.exitCode = 1; });
