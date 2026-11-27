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
  for (const width of [320, 375, 1870]) {
    const wide = width > 1000;
    const map = viewer(data, {width, height: wide ? 780 : 560, zoom: wide ? 7.5 : 6.75, center: [45.28, -93.79]});
    await map.load();
    assert.equal(map.get('metar-product').value, 'plots');
    for (const [i] of history.entries()) {
      map.frame(i);
      const names = ['Mankato', 'Redwood Falls', 'St. Cloud', 'Rochester'];
      if (i !== 2) names.push('Duluth');
      if (i !== 1) names.push('Twin Cities average');
      const additions = ['Albert Lea', 'Alexandria', 'Brainerd', 'Hutchinson', 'Mora', 'Red Wing', 'Willmar'];
      const visible = map.ids();
      assert.ok(names.every(name => visible.includes(name)), 'The original plots keep priority');
      assert.ok(visible.every(name => names.includes(name) || additions.includes(name)));
      if (wide) assert.deepEqual(visible, [...names, ...additions].sort());
      else assert.ok(additions.some(name => visible.includes(name)), 'More cities fit on narrow views too');
      const metro = map.marker('Twin Cities average');
      if (metro) {
        assert.deepEqual(Array.from(metro.position), [44.941104509329946, -93.3874108503608]);
        assert.equal(metro.popup.children[2].textContent, `Temperature: ${33 + i}.0°F`);
        assert.equal(metro.popup.children[3].textContent, `Dewpoint: ${18 + i}.0°F`);
        assert.ok(metro.popup.children.some(line => line.textContent.includes('KMSP · KFCM · KMIC')));
        assert.match(metro.icon.html, /data-mph="10"[^>]*rotate\(0\)/);
      }
      const mankato = map.marker('Mankato');
      assert.deepEqual(Array.from(mankato.position), [44.2184, -93.9179]);
      assert.equal(mankato.popup.children[0].textContent, 'Mankato (KMKT)');
      assert.equal(mankato.popup.children[2].textContent, `Temperature: ${40 + i}.0°F`);
      if (wide) assert.equal(map.marker('Brainerd').popup.children[2].textContent, `Temperature: ${29 + i}.0°F`);
    }
    await map.mode('clouds');
    assert.match(map.marker('KMSP').icon.html, /plot-sky/);
    assert.equal(map.marker('Twin Cities average'), undefined);
    await map.mode('plots');
    assert.match(map.marker('Mankato').icon.html, /plot-temp/);
    assert.ok(map.reads.every(url => url === '/api/station-plots?view=loop'));
  }
  console.log('METAR PLOTS shows the metro average and selected airport reports across Minnesota.');
})().catch(error => { console.error(error); process.exitCode = 1; });
