"use strict";
window.WeatherLampForecast = (() => {
  const timeOptions = {timeZone: "America/Chicago", hour: "numeric", minute: "2-digit"};
  const clock = new Intl.DateTimeFormat("en-US", timeOptions);
  const clockWithZone = new Intl.DateTimeFormat("en-US", {...timeOptions, timeZoneName:"short"});
  const day = new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago", weekday:"short", month:"short", day:"numeric"});
  const directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content != null) element.textContent = content;
    return element;
  }

  function windText(hour) {
    if (!Number.isFinite(hour.windMph)) return "—";
    const speed = Math.round(hour.windMph);
    if (speed === 0) return "Calm";
    const direction = Number.isFinite(hour.windDirection)
      ? directions[Math.round(hour.windDirection / 45) % 8] + " "
      : "";
    return direction + speed + " mph";
  }

  function render(lamp, now = Date.now()) {
    const root = document.getElementById("forecast-hourly");
    const hours = (lamp?.hours || []).filter(hour => Date.parse(hour.endTime) > now);
    root.replaceChildren();
    if (!hours.length) {
      root.append(node("p", "lamp-status", "LAMP guidance is temporarily unavailable."));
      return;
    }
    const note = node("p", "lamp-status", "KMSP · KFCM · KMIC · Conditions at the start of each hour. Precipitation chance covers the listed hour.");
    const list = node("div", "lamp-rows");
    const headings = node("div", "lamp-row lamp-headings");
    const labels = ["Central time", "Temperature", "Dewpoint", "Wind", "Sky cover", "Ceiling", "Precip. chance"];
    for (const label of labels) headings.append(node("span", null, label));
    list.append(headings);
    const format = (value, suffix) => Number.isFinite(value) ? Math.round(value) + suffix : "—";

    for (const hour of hours) {
      const start = new Date(hour.startTime);
      const end = new Date(hour.endTime);
      const endsOnNextDay = day.format(start) !== day.format(end);
      const crossesTimeChange = clockWithZone.format(start).slice(-3) !== clockWithZone.format(end).slice(-3);
      const formatter = crossesTimeChange ? clockWithZone : clock;
      const row = node("article", "lamp-row");
      const date = node("div", "lamp-when");
      date.append(node("span", null, day.format(start)),
        node("strong", null, formatter.format(start) + "–" + (endsOnNextDay ? "midnight" : formatter.format(end))));
      row.append(date);
      const values = [format(hour.temperatureF,"°F"), format(hour.dewpointF,"°F"), windText(hour),
        hour.skyCover || "—", hour.ceiling || "—", format(hour.precipChancePct,"%")];
      for (const [i, value] of values.entries()) {
        const field = node("div", "lamp-value");
        field.append(node("span", "lamp-mobile-label", labels[i+1]), node("strong", null, value));
        row.append(field);
      }
      list.append(row);
    }
    root.append(note, list);
  }

  return {render};
})();
