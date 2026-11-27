"use strict";

window.WeatherAvgMetar = (() => {
  const earthMiles = 3958.76;
  const radians = Math.PI / 180;
  const mphPerKnot = 1.150779;
  const metroAirports = [
    {id: "KMSP", lat: 44.8852, lon: -93.2313},
    {id: "KFCM", lat: 44.8321, lon: -93.4705},
    {id: "KMIC", lat: 45.0623, lon: -93.3511},
  ];
  // Display order also gives the larger cities priority when plots crowd at wide zooms.
  const cities = [
    ["KMKT", "Mankato"],
    ["KSTC", "St. Cloud"],
    ["KDLH", "Duluth"],
    ["KRWF", "Redwood Falls"],
    ["KRST", "Rochester"],
    ["KEAU", "Eau Claire"],
    ["KBRD", "Brainerd"],
    ["KBJI", "Bemidji"],
    ["KAXN", "Alexandria"],
    ["KFAR", "Fargo"],
    ["KFSD", "Sioux Falls"],
    ["KLSE", "La Crosse"],
    ["KDSM", "Des Moines"],
    ["KMSN", "Madison"],
    ["KGRB", "Green Bay"],
    ["KMKE", "Milwaukee"],
    ["KGFK", "Grand Forks"],
    ["KABR", "Aberdeen"],
    ["KCID", "Cedar Rapids"],
    ["KSUX", "Sioux City"],
    ["KALO", "Waterloo"],
    ["KDBQ", "Dubuque"],
    ["KAUW", "Wausau"],
    ["KBDH", "Willmar"],
    ["KGPZ", "Grand Rapids"],
    ["KHIB", "Hibbing"],
    ["KDTL", "Detroit Lakes"],
    ["KFFM", "Fergus Falls"],
    ["KTVF", "Thief River Falls"],
    ["KINL", "International Falls"],
    ["KCKC", "Grand Marais"],
    ["KHCD", "Hutchinson"],
    ["KULM", "New Ulm"],
    ["KMML", "Marshall"],
    ["KOTG", "Worthington"],
    ["KFRM", "Fairmont"],
    ["KAEL", "Albert Lea"],
    ["KFBL", "Faribault"],
    ["KRGK", "Red Wing"],
    ["KATY", "Watertown"],
    ["KJMS", "Jamestown"],
    ["KMCW", "Mason City"],
    ["KSPW", "Spencer"],
    ["KASX", "Ashland"],
    ["KRHI", "Rhinelander"],
  ];
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

  const centerVector = xyz(...center);
  const metroPoint = {station: "AVG-METRO", name: "Metro", lat: center[0], lon: center[1]};

  function nearestNeighbors(local, reports) {
    const nearest = [];
    for (const report of reports) {
      if (report.station === local.station) continue;
      const distance = chordSquared(local.vector, report.vector);
      const index = nearest.findIndex(item => distance < item.distance);
      if (index !== -1) nearest.splice(index, 0, {report, distance});
      else if (nearest.length < 2) nearest.push({report, distance});
      if (nearest.length > 2) nearest.pop();
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

  function cityWeights(neighbors) {
    // Half belongs to the city's airport. Split the rest by inverse distance.
    const [first, second] = neighbors.map(source => 1 / Math.max(1, source.miles));
    const total = first + second;
    return [.5, .5 * first / total, .5 * second / total];
  }

  function average(point, sources, time, metro = false) {
    const contributors = sources.map(({report, distance}) => ({
      station: report.station,
      miles: miles(distance),
      report,
      wind: stationWind(report.wind),
    }));
    const weights = metro ? [1 / 3, 1 / 3, 1 / 3] : cityWeights(contributors.slice(1));
    contributors.forEach((source, i) => { source.weight = weights[i]; });
    function mean(read) {
      const values = contributors.map(source => read(source.report));
      return values.every(Number.isFinite)
        ? contributors.reduce((sum, source, i) => sum + source.weight * values[i], 0)
        : null;
    }
    return {
      ...point, time, metro,
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
      for (const [id, name] of cities) {
        const local = byId.get(id);
        if (!local) continue;
        const point = {station: `AVG-${id}`, name, lat: local.lat, lon: local.lon};
        const sources = [{report: local, distance: 0}, ...nearestNeighbors(local, uniqueReports)];
        points.push(average(point, sources, frame.hour));
      }
    }
    cache.set(frame, points);
    return points;
  }

  return {center, estimates};
})();
