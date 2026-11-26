'use strict';
const assert = require('node:assert/strict');
const viewer = require('./metro_viewer');

const airports = [
  {station: 'KMSP', lat: 44.8831, lon: -93.2289},
  {station: 'KFCM', lat: 44.8272, lon: -93.4571},
  {station: 'KMIC', lat: 45.0619, lon: -93.3539},
];
const history = Array.from({length: 4}, (_, hour) => ({
  hour: new Date(Date.UTC(2026, 10, 17, 15 + hour)).toISOString(),
  stations: airports.map((airport, i) => ({
    ...airport,
    reportType: 'METAR',
    time: new Date(Date.UTC(2026, 10, 17, 14 + hour, 53)).toISOString(),
    tempF: 70 + 4 * hour + i,
    dewpointF: 40 + 4 * hour + i,
    wind: {speedMph: 5 + 5 * i, direction: 90 * (i + 1)},
    layers: [{cover: 'BKN', baseFtAGL: 2000 + 1000 * i}],
  })),
}));
// A missing KMIC report should only remove the center for that frame.
history[1].stations.pop();
for (const frame of history) {
  const msp = frame.stations.find(s => s.station === 'KMSP');
  frame.stations.push(
    {...msp, station: 'KNEAR', lat: 44.884, tempF: 31, dewpointF: 30},
    {...msp, station: 'KSTP', lat: 44.9345, lon: -93.0600},
  );
}
const data = {checkedAt: '2026-11-17T18:02:00Z', history};
(async () => {
  for (const width of [320, 375, 1870]) {
    const map = viewer(data, {width, zoom: 8});
    await map.load();
    assert.equal(map.get('metar-product').value, 'avgmetar');
    for (const [i] of history.entries()) {
      map.frame(i);
      assert.equal(Boolean(map.marker('AVG-METRO')), i !== 1);
      assert.ok(map.ids().length && map.ids().every(id => id.startsWith('AVG-')));
    }
    await map.mode('clouds');
    assert.ok(map.ids().includes('KMSP'), 'CLOUDS still uses the original KMSP report');
    await map.mode('plots');
    assert.equal(map.get('metar-product').value, 'avgmetar');
    assert.ok(map.ids().every(id => id.startsWith('AVG-')));
    assert.ok(map.reads.every(url => url === '/api/station-plots?view=loop'));
  }
  console.log('METAR PLOTS uses averages only, with the original CLOUDS reports available.');
})().catch(error => { console.error(error); process.exitCode = 1; });
