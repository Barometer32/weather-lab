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
    time: new Date(Date.UTC(2026, 10, 17, 14 + hour, 53)).toISOString(),
    tempF: 70 + 4 * hour + i,
    dewpointF: 40 + 4 * hour + i,
    wind: {speedMph: 5 + 5 * i, direction: 90 * (i + 1)},
    layers: [{cover: 'BKN', baseFtAGL: 2000 + 1000 * i}],
  })),
}));
// A missing KMIC report should affect only this frame. The nearby airport
// competes for KMSP's plot space without sharing its identifier.
history[1].stations.pop();
for (const frame of history) {
  frame.stations.push({station: 'KNEAR', lat: 44.884, lon: -93.2289, tempF: 31, dewpointF: 30});
}
const data = {checkedAt: '2026-11-17T18:02:00Z', history};

(async () => {
  for (const width of [320, 375, 1870]) {
    const map = viewer(data, {width});
    await map.load();
    assert.equal(map.get('metar-product').value, 'plots');
    for (const [i, frame] of history.entries()) {
      map.frame(i);
      assert.deepEqual(map.ids(), frame.stations.filter(s => s.station !== 'KNEAR').map(s => s.station).sort());
      for (const station of frame.stations.filter(s => s.station !== 'KNEAR')) {
        const marker = map.marker(station.station);
        assert.deepEqual(Array.from(marker.position), [station.lat, station.lon]);
        const popup = marker.popup.children.map(node => node.textContent);
        assert.equal(popup[0], station.station);
        assert.ok(popup.includes(`Temperature: ${station.tempF}.0°F`));
        assert.ok(popup.includes(`Dewpoint: ${station.dewpointF}.0°F`));
        assert.ok(popup.includes(`Wind: ${station.wind.speedMph} mph from ${station.wind.direction}°`));
        assert.match(marker.icon.html, new RegExp(`rotate\\(${station.wind.direction}\\)`));
      }
    }
    assert.deepEqual(map.reads, ['/api/station-plots?view=loop']);
  }
  console.log('METAR PLOTS shows each metro airport’s own readings, location, and wind for each available hour.');
})().catch(error => { console.error(error); process.exitCode = 1; });
