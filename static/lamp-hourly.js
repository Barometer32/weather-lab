"use strict";
window.WeatherLamp = (() => {
  const $ = id => document.getElementById(id);
  const endpoint = "/api/hourly";
  const directions = ["N","NE","E","SE","S","SW","W","NW"];
  const fullTime = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago", month:"short", day:"numeric", hour:"numeric", minute:"2-digit", timeZoneName:"short"});
  const temp = value => value == null ? "—" : `${value}°F`;
  let active = false;
  let hourlyBusy = false, hourlyData, hourlyError;
  const hourlyDay = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago", month:"short", day:"numeric"});
  const hourlyClock = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago", hour:"numeric"});

  function renderHourly() {
    if (!active) return;
    const rows = (hourlyData?.rows || []).filter(row => new Date(row.endTime).getTime() > Date.now());
    $("hourly-cycle").textContent = hourlyData ? `LAMP run ${fullTime.format(new Date(hourlyData.cycle))}` : (hourlyError ? "Hourly data unavailable" : "Loading the latest LAMP run…");
    const status = hourlyError || (hourlyData?.stale ? "The latest LAMP run is delayed." : "");
    $("hourly-status").hidden = !status && rows.length > 0;
    $("hourly-status").textContent = status || "No upcoming hourly forecast rows are available.";
    $("hourly-table").hidden = rows.length === 0;
    const rendered = document.createDocumentFragment();
    let previousDay;
    for (const row of rows) {
      const tr = document.createElement("tr");
      const hour = document.createElement("th");
      hour.scope = "row";
      const valid = new Date(row.time);
      const day = hourlyDay.format(valid);
      if (day !== previousDay) {
        const dayLabel = document.createElement("small");
        dayLabel.textContent = day;
        hour.append(dayLabel);
      }
      previousDay = day;
      const clock = document.createElement("time");
      clock.dateTime = row.time;
      clock.title = fullTime.format(valid);
      clock.textContent = hourlyClock.format(valid);
      hour.append(clock);
      tr.append(hour);

      const speed = row.windMph;
      const blendedWind = speed == null ? "—" : speed <= 3 ? "Calm" :
        `${row.windDirection == null ? "VRB" : directions[Math.round(row.windDirection / 45) % 8]} ${speed} mph`;
      for (const value of [temp(row.tempF), temp(row.dewpointF), blendedWind]) {
        const cell = tr.insertCell();
        cell.textContent = value;
      }
      const cloud = tr.insertCell();
      cloud.textContent = row.cloudCover || "—";
      if (row.ceiling) {
        const ceiling = document.createElement("small");
        ceiling.title = row.ceiling === ">12k" ? "Above 12,000 feet or unlimited" : "Estimated average ceiling above ground";
        ceiling.textContent = `${row.ceiling} ft`;
        cloud.append(ceiling);
      }
      const precip = tr.insertCell();
      precip.className = "hourly-precip";
      precip.textContent = row.precipChance == null ? "—" : `${row.precipChance}%`;
      precip.title = `${fullTime.format(valid)} to ${fullTime.format(new Date(row.endTime))}`;
      rendered.append(tr);
    }
    $("hourly-rows").replaceChildren(rendered);
  }

  async function loadHourly(force = false) {
    if (hourlyBusy) return;
    hourlyBusy = true;
    $("refresh-hourly").disabled = true;
    try {
      hourlyData = await window.WeatherPrepared.read(endpoint, {force});
      hourlyError = null;
    } catch (error) {
      hourlyError = error.message;
    } finally {
      hourlyBusy = false;
      $("refresh-hourly").disabled = false;
      renderHourly();
    }
  }

  $("refresh-hourly").addEventListener("click", () => loadHourly(true));
  window.WeatherPrepared.subscribe(endpoint, data => {
    hourlyData = data;
    hourlyError = null;
    renderHourly();
  });
  setInterval(() => {
    if (active && !document.hidden) loadHourly();
  }, 60000);
  return {
    select(id) {
      active = id === "hourly";
      if (active) loadHourly();
    },
    refresh() {
      if (active) loadHourly();
    },
  };
})();
