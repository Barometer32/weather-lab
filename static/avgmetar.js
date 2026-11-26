"use strict";

window.WeatherAvgMetar = (() => {
  const earthMiles = 3958.76;
  const radians = Math.PI / 180;
  const spacing = 30;
  const metroAirports = [
    {id: "KMSP", lat: 44.8852, lon: -93.2313},
    {id: "KFCM", lat: 44.8321, lon: -93.4705},
    {id: "KMIC", lat: 45.0623, lon: -93.3511},
  ];
  const bounds = [[40, -100], [50, -85]];
  const xyz = (lat, lon) => [
    Math.cos(lat * radians) * Math.cos(lon * radians),
    Math.cos(lat * radians) * Math.sin(lon * radians),
    Math.sin(lat * radians),
  ];
  const chordSquared = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2;
  const miles = distance => 2 * earthMiles * Math.asin(Math.min(1, Math.sqrt(distance) / 2));

  // The normal to the plane through the three airports is equidistant from
  // all three on the sphere. Choose its Minnesota-facing end.
  const [a, b, c] = metroAirports.map(({lat, lon}) => xyz(lat, lon));
  const [u, v, w] = b.map((value, i) => value - a[i]);
  const [x, y, z] = c.map((value, i) => value - a[i]);
  let normal = [v * z - w * y, w * x - u * z, u * y - v * x];
  if (normal.reduce((dot, value, i) => dot + value * a[i], 0) < 0) normal = normal.map(value => -value);
  const center = Object.freeze([
    Math.atan2(normal[2], Math.hypot(normal[0], normal[1])) / radians,
    Math.atan2(normal[1], normal[0]) / radians,
  ]);

  function gridPosition(east, north) {
    const [lat, lon] = center.map(value => value * radians);
    const heading = Math.atan2(east, north);
    const arc = Math.hypot(east, north) * spacing / earthMiles;
    const nextLat = Math.asin(Math.sin(lat) * Math.cos(arc) + Math.cos(lat) * Math.sin(arc) * Math.cos(heading));
    const nextLon = lon + Math.atan2(Math.sin(heading) * Math.sin(arc) * Math.cos(lat),
      Math.cos(arc) - Math.sin(lat) * Math.sin(nextLat));
    return [nextLat / radians, nextLon / radians];
  }

  const centerVector = xyz(...center);
  const metroPoint = {station: "AVG-METRO", lat: center[0], lon: center[1], east: 0, north: 0};
  const [[south, west], [north, east]] = bounds;
  const extent = Math.ceil(Math.max(...[south, north].flatMap(lat =>
    [west, east].map(lon => miles(chordSquared(centerVector, xyz(lat, lon)))))) / spacing);
  const grid = [];
  for (let row = -extent; row <= extent; row++) {
    for (let col = -extent; col <= extent; col++) {
      if (row === 0 && col === 0) continue;
      const [lat, lon] = gridPosition(col, row);
      if (lat >= south && lat <= north && lon >= west && lon <= east) {
        grid.push({station: `AVG-${col},${row}`, lat, lon, east: col, north: row, vector: xyz(lat, lon)});
      }
    }
  }

  function nearestThree(point, reports) {
    const nearest = [];
    for (const report of reports) {
      const distance = chordSquared(point.vector, report.vector);
      const index = nearest.findIndex(item => distance < item.distance);
      if (index !== -1) nearest.splice(index, 0, {report, distance});
      else if (nearest.length < 3) nearest.push({report, distance});
      if (nearest.length > 3) nearest.pop();
    }
    return nearest;
  }

  function average(point, sources, time, metro = false) {
    const contributors = sources.map(({report, distance}) => ({
      station: report.station,
      miles: miles(distance),
      report,
    }));
    const weights = contributors.map(source => metro ? 1 : 1 / Math.max(1, source.miles));
    const total = weights.reduce((sum, weight) => sum + weight, 0);
    contributors.forEach((source, i) => { source.weight = weights[i] / total; });
    function mean(read) {
      const values = contributors.map(source => read(source.report));
      return values.every(Number.isFinite)
        ? contributors.reduce((sum, source, i) => sum + source.weight * values[i], 0)
        : null;
    }
    const speed = report => report.wind?.speedMph ?? (Number.isFinite(report.wind?.speedKnots) ? report.wind.speedKnots * 1.150779 : null);
    const speedMph = mean(speed);
    let sin = 0, cos = 0;
    for (const source of contributors) {
      const direction = source.report.wind?.direction;
      if (!Number.isFinite(direction) || source.report.wind?.variable) continue;
      const strength = source.weight * (speed(source.report) ?? 0);
      sin += strength * Math.sin(direction * radians);
      cos += strength * Math.cos(direction * radians);
    }
    const direction = Math.hypot(sin, cos) > .01 ? (Math.atan2(sin, cos) / radians + 360) % 360 : null;
    return {
      station: point.station, lat: point.lat, lon: point.lon, east: point.east, north: point.north, time, metro,
      tempF: mean(report => report.tempF),
      dewpointF: mean(report => report.dewpointF),
      wind: {speedMph, direction, variable: speedMph > 0 && direction === null},
      contributors: contributors.map(({station, miles, weight}) => ({station, miles, weight})),
    };
  }

  const cache = new WeakMap();
  function estimates(frame) {
    const saved = cache.get(frame);
    if (saved) return saved;
    const reports = frame.stations
      .filter(report => report.reportType === "METAR" && report.station !== "KSTP"
        && [report.lat, report.lon, report.tempF].every(Number.isFinite))
      .map(report => ({...report, vector: xyz(report.lat, report.lon)}))
      .sort((first, second) => first.station.localeCompare(second.station));
    const byId = new Map(reports.map(report => [report.station, report]));
    const metro = metroAirports.map(({id}) => byId.get(id));
    const points = metro.every(Boolean) ? [average(metroPoint,
      metro.map(report => ({report, distance: chordSquared(centerVector, report.vector)})), frame.hour, true)] : [];
    if (byId.size >= 3) {
      const uniqueReports = [...byId.values()];
      for (const point of grid) points.push(average(point, nearestThree(point, uniqueReports), frame.hour));
    }
    cache.set(frame, points);
    return points;
  }

  return {center, nextEast: gridPosition(1, 0), nextNorth: gridPosition(0, 1), estimates};
})();
