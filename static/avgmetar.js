"use strict";

window.WeatherAvgMetar = (() => {
  const earthMiles = 3958.76;
  const radians = Math.PI / 180;
  const spacing = 25;
  const mphPerKnot = 1.150779;
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

  function stationWind(wind) {
    const knots = wind?.speedKnots;
    const mph = Number.isFinite(knots) && knots >= 0 ? knots * mphPerKnot : wind?.speedMph;
    const speedMph = Number.isFinite(mph) && mph >= 0 ? mph : null;
    const bearing = wind?.direction;
    const variable = wind?.variable === true;
    const direction = speedMph > 0 && !variable && Number.isFinite(bearing) && bearing >= 0 && bearing <= 360
      ? bearing % 360 : null;
    return {speedMph, direction, variable};
  }

  function averageWind(contributors) {
    let east = 0, north = 0, vectorWeight = 0, directed = 0, vectorCount = 0;
    let speedSum = 0, speedWeight = 0, variable = false;
    for (const {wind, weight} of contributors) {
      const {speedMph, direction} = wind;
      if (speedMph === null) continue;
      speedSum += speedMph * weight;
      speedWeight += weight;
      if (speedMph === 0 || direction !== null) {
        vectorWeight += weight;
        vectorCount++;
      }
      if (direction !== null) {
        east += weight * speedMph * Math.sin(direction * radians);
        north += weight * speedMph * Math.cos(direction * radians);
        directed++;
      }
      variable ||= wind.variable;
    }
    const meanSpeedMph = speedWeight > 0 ? speedSum / speedWeight : null;
    // Speeds with no bearing contribute only to the scalar mean. Calm reports
    // count as zero vectors, and a directed result uses one vector for both fields.
    if (!directed) return {speedMph: meanSpeedMph, direction: null, variable, meanSpeedMph, vectorCount};
    const speedMph = Math.hypot(east, north) / vectorWeight;
    const direction = speedMph >= .05 ? (Math.atan2(east, north) / radians + 360) % 360 : null;
    return {speedMph: direction === null ? 0 : speedMph, direction, variable: false, meanSpeedMph, vectorCount};
  }

  function average(point, sources, time, metro = false) {
    const contributors = sources.map(({report, distance}) => ({
      station: report.station,
      miles: miles(distance),
      report,
      wind: stationWind(report.wind),
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
    return {
      station: point.station, lat: point.lat, lon: point.lon, east: point.east, north: point.north, time, metro,
      tempF: mean(report => report.tempF),
      dewpointF: mean(report => report.dewpointF),
      wind: averageWind(contributors),
      contributors: contributors.map(({station, miles, weight, wind}) => ({station, miles, weight, wind})),
    };
  }

  const cache = new WeakMap();
  function estimates(frame) {
    const saved = cache.get(frame);
    if (saved) return saved;
    const reports = frame.stations
      .filter(report => report.reportType === "METAR"
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

  return {center, spacing, nextEast: gridPosition(1, 0), nextNorth: gridPosition(0, 1), estimates};
})();
