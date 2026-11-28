"use strict";

window.WeatherMetarPlots = (() => {
  const metroAirports = ["KMSP", "KFCM", "KMIC"];
  const metroId = "AVG-METRO";
  // Same equidistant point used for the original three-airport average.
  const metroCenter = [44.941104509329946, -93.3874108503608];
  const primaryCities = [
    ["KMKT", "Mankato", [44.2184, -93.9179]],
    ["KRWF", "Redwood Falls", [44.5483, -95.0804]],
    ["KSTC", "St. Cloud", [45.5442, -94.0516]],
    ["KRST", "Rochester", [43.904, -92.4921]],
    ["KDLH", "Duluth", [46.8435, -92.1866]],
  ];
  const initialCities = [
    ...primaryCities,
    ["KAEL", "Albert Lea", [43.6823, -93.3722]],
    ["KAXN", "Alexandria", [45.8680, -95.3940]],
    ["KBRD", "Brainerd", [46.4021, -94.1273]],
    ["KHCD", "Hutchinson", [44.8597, -94.3855]],
    ["KJMR", "Mora", [45.8885, -93.2690]],
    ["KRGK", "Red Wing", [44.5926, -92.4844]],
    ["KBDH", "Willmar", [45.1111, -95.1258]],
  ];
  // Choose real airport locations to fill the regional gaps at similar intervals.
  const cities = [
    ...initialCities,
    // Minnesota
    ["KBJI", "Bemidji"],
    ["KFFM", "Fergus Falls"],
    ["KCKC", "Grand Marais"],
    ["KHIB", "Hibbing"],
    ["KINL", "International Falls"],
    ["KTVF", "Thief River Falls"],
    ["KOTG", "Worthington"],
    // North and South Dakota
    ["KFAR", "Fargo"],
    ["KGFK", "Grand Forks"],
    ["KABR", "Aberdeen"],
    ["KFSD", "Sioux Falls"],
    ["KATY", "Watertown"],
    // Wisconsin
    ["KASX", "Ashland"],
    ["KEAU", "Eau Claire"],
    ["KGRB", "Green Bay"],
    ["KLSE", "La Crosse"],
    ["KMSN", "Madison"],
    ["KMKE", "Milwaukee"],
    ["KRHI", "Rhinelander"],
    ["KRPD", "Rice Lake"],
    ["KAUW", "Wausau"],
    // Iowa
    ["KDBQ", "Dubuque"],
    ["KFOD", "Fort Dodge"],
    ["KMCW", "Mason City"],
    ["KSUX", "Sioux City"],
    ["KSPW", "Spencer"],
    ["KALO", "Waterloo"],
  ];
  const priority = [metroId, ...primaryCities.map(([id]) => id)];
  const regionalHubs = ["KMKE", "KMSN", "KFAR", "KFSD", "KGRB", "KSUX", "KALO", "KEAU", "KLSE", "KGFK", "KAUW", "KBJI"];
  const names = new Map(cities.map(([id, name]) => [id, name]));
  names.set(metroId, "Twin Cities average");
  const locations = [metroCenter, ...initialCities.map(([, , location]) => location)];
  const radians = Math.PI / 180;

  function averageWind(stations) {
    let east = 0, north = 0, vectorCount = 0, directed = false;
    let totalSpeed = 0, speedCount = 0, variable = false;
    for (const {wind} of stations) {
      const knots = wind?.speedKnots;
      const speed = Number.isFinite(knots) && knots >= 0 ? knots * 1.150779 : wind?.speedMph;
      if (!Number.isFinite(speed) || speed < 0) continue;
      totalSpeed += speed;
      speedCount++;
      variable ||= wind.variable === true;
      if (speed === 0) {
        vectorCount++;
        continue;
      }
      const bearing = wind.direction;
      if (wind.variable || !Number.isFinite(bearing) || bearing < 0 || bearing > 360) continue;
      east += speed * Math.sin(bearing * radians);
      north += speed * Math.cos(bearing * radians);
      vectorCount++;
      directed = true;
    }
    // Variable winds contribute speed when no directed wind is available.
    // Calm reports count as zero vectors in a directed average.
    if (!directed) return {speedMph: speedCount ? totalSpeed / speedCount : null, direction: null, variable};
    const speedMph = Math.hypot(east, north) / vectorCount;
    if (speedMph < .05) return {speedMph: 0, direction: null, variable: false};
    return {speedMph, direction: (Math.atan2(east, north) / radians + 360) % 360, variable: false};
  }

  function reports(frame) {
    const byId = new Map(frame.stations.filter(report => report.reportType === "METAR")
      .map(report => [report.station, report]));
    const metro = metroAirports.map(id => byId.get(id));
    const plots = cities.map(([id]) => byId.get(id)).filter(Boolean);
    if (metro.every(report => Number.isFinite(report?.tempF))) {
      plots.unshift({
        station: metroId, lat: metroCenter[0], lon: metroCenter[1], time: frame.hour,
        tempF: metro.reduce((sum, report) => sum + report.tempF, 0) / metro.length,
        dewpointF: metro.every(report => Number.isFinite(report.dewpointF))
          ? metro.reduce((sum, report) => sum + report.dewpointF, 0) / metro.length : null,
        wind: averageWind(metro),
      });
    }
    return plots;
  }

  return {metroId, metroAirports, locations, names, priority, regionalHubs, reports};
})();
