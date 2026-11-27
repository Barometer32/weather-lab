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
// A missing KMIC report affects only that station and hour.
history[1].stations.pop();
for (const frame of history) {
  const msp = frame.stations.find(s => s.station === 'KMSP');
  frame.stations.push(
    {...msp, station: 'KNEAR', lat: 44.884, tempF: 31, dewpointF: 30},
    {...msp, station: 'KSTP', lat: 44.9345, lon: -93.0600},
    {...msp, station: 'KMKT', lat: 44.2184, lon: -93.9179},
    {...msp, station: 'KULM', lat: 44.3227, lon: -94.5024},
  );
}
const data = {checkedAt: '2026-11-17T18:02:00Z', history};
(async () => {
  for (const width of [320, 375, 1870]) {
    const map = viewer(data, {width, zoom: 9.5});
    await map.load();
    assert.equal(map.get('metar-product').value, 'plots');
    for (const [i] of history.entries()) {
      map.frame(i);
      const msp = map.marker('KMSP');
      assert.ok(msp && map.marker('KSTP') && map.marker('KFCM'));
      assert.equal(Boolean(map.marker('KMIC')), i !== 1);
      assert.ok(!map.marker('KNEAR'), 'KMSP has priority over an overlapping airport');
      assert.equal(msp.popup.children[2].textContent, `Temperature: ${70 + 4 * i}.0°F`);
      assert.deepEqual(Array.from(msp.position), [airports[0].lat, airports[0].lon]);
      assert.match(msp.icon.html, /data-mph=/);
      assert.ok(map.ids().every(id => history[i].stations.some(s => s.station === id)));
    }
    await map.mode('clouds');
    assert.match(map.marker('KMSP').icon.html, /plot-sky/);
    await map.mode('avgmetar');
    assert.equal(map.get('metar-product').value, 'plots');
    assert.match(map.marker('KSTP').icon.html, /plot-temp/);
    assert.ok(map.reads.every(url => url === '/api/station-plots?view=loop'));
  }
  console.log('METAR PLOTS shows individual reports, including KMSP and KSTP, with independent hourly eligibility.');
})().catch(error => { console.error(error); process.exitCode = 1; });
