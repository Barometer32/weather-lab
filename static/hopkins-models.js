(() => {
  const pick = document.getElementById("models-source");
  const rows = document.getElementById("models-rows");
  const run = document.getElementById("models-run");
  const time = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago", weekday: "short", hour: "numeric", minute: "2-digit"
  });
  const runDate = new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC", month: "short", day: "numeric", hour: "2-digit", hourCycle: "h23"
  });
  const dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
  let data, pending;
  function utc(iso) {
    const parts = Object.fromEntries(runDate.formatToParts(new Date(iso)).map(p => [p.type,p.value]));
    return parts.month + " " + parts.day + ", " + parts.hour + "Z";
  }
  function render() {
    if (!data) return;
    const source = pick.value;
    run.textContent = "Fixed " + utc(data.run) + " run · RRFS cloud profile from " + utc(data.rrfsCloudRun) + " · Central time";
    const fragment = document.createDocumentFragment();
    for (const row of data.rows) {
      const entry = source === "blend" ? row.blend : row.models[source];
      const wind = entry.windDegrees == null ? "Calm" :
        dirs[Math.round(entry.windDegrees/22.5)%16] + " " + Math.round(entry.windMph) + " mph";
      const values = [
        time.format(new Date(row.valid)), Math.round(entry.tempF) + "°F", Math.round(entry.dewF) + "°F",
        wind, ...["low","mid","high"].map(key => Math.round(entry[key]) + "%"),
        (entry.precipIn > 0 && entry.precipIn < .005 ? "<0.01" : entry.precipIn.toFixed(2)) + " in"
      ];
      const tr = document.createElement("tr");
      values.forEach((value, i) => {
        const cell = document.createElement(i === 0 ? "th" : "td");
        if (!i) cell.scope = "row";
        cell.textContent = value;
        if (!i) {
          const z = document.createElement("small");
          z.className = "models-utc";
          z.textContent = new Date(row.valid).toISOString().slice(11,13) + "Z";
          cell.appendChild(z);
        }
        if (i === 7) cell.title = new Date(row.valid).toISOString().slice(11,16) + "–" +
          new Date(row.precipEnds).toISOString().slice(11,16) + " UTC";
        tr.appendChild(cell);
      });
      fragment.appendChild(tr);
    }
    rows.replaceChildren(fragment);
    document.getElementById("models-note").textContent =
      "Temperature and dew point at 2 m; wind at 10 m. The blend averages wind vectors and gives each model one-third weight. " +
      "Cloud percentages are experimental estimates from the vertical profiles. Precipitation is liquid equivalent for the hour starting at the listed time.";
  }
  pick.addEventListener("change", render);
  function load() {
    if (data || pending) return pending;
    pending = fetch("/static/hopkins-models.json?v=20261109-23")
      .then(res => { if (!res.ok) throw new Error(); return res.json(); })
      .then(result => { data = result; render(); })
      .catch(() => { run.textContent = "The saved model forecast could not be loaded. Switch tabs and try again."; })
      .finally(() => { pending = null; });
    return pending;
  }
  window.WeatherHopkinsModels = {load};
})();
