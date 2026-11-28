"use strict";
window.WeatherHrmetar = (() => {
  const el = id => document.getElementById(id);
  const endpoint = "/api/hrmetar";
  const date = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
  });
  const maxAgeMs = 30 * 60 * 1000;
  const directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  const fahrenheit = celsius => Number.isFinite(celsius) ? `${Math.round(celsius * 9 / 5 + 32)}°F` : "—";
  let active = false, busy = false, current;

  function render(message) {
    if (current && Date.now() - Date.parse(current.observedAt) > maxAgeMs) current = null;
    el("hrmetar-temperature").textContent = fahrenheit(current?.tempC);
    el("hrmetar-dewpoint").textContent = fahrenheit(current?.dewpointC);
    const speed = current?.windMph, bearing = current?.windDirection;
    const heading = Number.isFinite(bearing) ? directions[Math.round(bearing / 45) % 8] : "VRB";
    el("hrmetar-wind").textContent = Number.isFinite(speed) ? (speed <= 3 ? "CALM" : `${heading} ${speed} mph`) : "—";
    if (!current?.observedAt) {
      el("hrmetar-observed-time").textContent = message || "Waiting for a five-minute report from all three airports.";
      return;
    }
    const observed = new Date(current.observedAt);
    const age = Math.max(0, Math.floor((Date.now() - observed.getTime()) / 60000));
    el("hrmetar-observed-time").textContent = `${date.format(observed)} · ${age} min old${message ? " · " + message : ""}`;
  }

  function adopt(data) {
    if (!current || !data.current || data.current.observedAt >= current.observedAt) current = data.current;
    if (active) render();
  }

  async function load(force = false) {
    if (busy) return;
    busy = true;
    const button = el("refresh-hrmetar-observations");
    button.disabled = true;
    try {
      const data = await window.WeatherPrepared.read(endpoint, {force});
      adopt(data);
    } catch {
      if (active) render("Five-minute reports are temporarily unavailable.");
    } finally {
      busy = false;
      button.disabled = false;
    }
  }

  el("refresh-hrmetar-observations").addEventListener("click", () => load(true));
  window.WeatherPrepared.subscribe(endpoint, adopt);
  setInterval(() => { if (active && !document.hidden) load(); }, 60000);
  return {
    select(id) {
      active = id === "hrmetar";
      if (active) load();
    },
    refresh() { if (active) load(); },
  };
})();
