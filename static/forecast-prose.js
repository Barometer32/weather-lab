"use strict";
const WeatherForecastProse = (() => {
  const timezone = "America/Chicago";
  const clock = new Intl.DateTimeFormat("en-US", {timeZone: timezone, hour:"numeric", minute:"2-digit"});
  const zone = new Intl.DateTimeFormat("en-US", {timeZone: timezone, timeZoneName:"short"});
  const wet = /\b(?:rain|showers?|drizzle|snow|flurries|sleet|thunderstorms?|hail|wintry mix)\b/i;
  const phenomenon = "(?:freezing rain|freezing drizzle|rain showers?|snow showers?|rain|drizzle|snow|flurries|sleet|showers?|thunderstorms?)";
  const coverage = "(?:(?:a )?(?:slight chance|chance|periods|areas) of |scattered |isolated |numerous |widespread |occasional |intermittent |patchy |frequent |brief )?";
  const intensity = "(?:very light|light|moderate|heavy)";
  const simple = new RegExp(`^(${coverage})(${intensity} )?(${phenomenon})( likely)?(?: \\((${intensity})\\))?$`);
  const startsWithWet = new RegExp(`^${coverage}(?:(?:a )?(?:\\d+ percent|\\d+%) chance of )?(?:${intensity} )?${phenomenon}\\b`, "i");
  const time = value => clock.format(value).replace(":00", "");
  const capitalize = text => text[0].toUpperCase() + text.slice(1);
  const timeZone = value => zone.formatToParts(value).find(part => part.type === "timeZoneName").value;

  function wetPhrase(window) {
    const hourly = window.condition?.toLowerCase() || "";
    if (!wet.test(hourly) && !(window.weather || []).some(label => wet.test(label))) return "";
    // Hourly labels often omit "of"; the gridded wording may include coverage and intensity.
    const wording = hourly.replace(/^(slight chance|chance) (?!of )/, "$1 of ");
    const hourlyMatch = wording.match(simple);
    // Preserve the official text for mixed or transitional labels we cannot safely rewrite.
    if (!hourlyMatch) return null;
    const grid = window.weather?.length === 1 ? window.weather[0].toLowerCase().match(simple) : null;
    const compatible = grid && (grid[3] === hourlyMatch[3] || (grid[3] === "rain showers" && hourlyMatch[3] === "showers"));
    const [, prefix, strength, type, likely, parenthetical] = compatible ? grid : hourlyMatch;
    const chance = window.maxChancePct;
    const probability = prefix || likely || !Number.isFinite(chance) || chance < 15 || chance >= 80 ? ""
      : chance < 30 ? "slight chance of " : chance < 60 ? "chance of " : "";
    const article = /^(?:slight chance|chance) of $/.test(prefix || probability) ? "a " : "";
    const suffix = likely || (!prefix && chance >= 60 && chance < 80 ? " likely" : "");
    return article + (prefix || probability) + (parenthetical ? parenthetical + " " : strength || "") + type + suffix;
  }

  function formatRange(start, end) {
    const leftZone = timeZone(start), rightZone = timeZone(end);
    return leftZone === rightZone ? `from ${time(start)} to ${time(end)}` : `from ${time(start)} ${leftZone} to ${time(end)} ${rightZone}`;
  }

  function forecastTiming(period, now) {
    const periodStart = Date.parse(period.startTime), periodEnd = Date.parse(period.endTime);
    const start = Math.max(periodStart, now), end = periodEnd;
    if (!(start < end)) return "";
    const windows = (period.hourlyWindows || []).filter(w => Date.parse(w.endTime) > start);
    const spells = [];
    let covered = start;
    for (const window of windows) {
      const from = Date.parse(window.startTime), to = Date.parse(window.endTime);
      if (!(from <= covered && to > covered && to <= end)) return "";
      const phrase = wetPhrase(window);
      if (phrase === null) return "";
      const previous = spells.at(-1);
      if (previous?.phrase === phrase) previous.end = to;
      else spells.push({phrase, start: covered, end: to});
      covered = to;
    }
    if (covered !== end) return "";
    const clauses = spells.filter(spell => spell.phrase).map(spell => {
      if (spell.start === start && spell.end === end) return spell.phrase;
      if (spell.start === start) return `${spell.phrase} before ${time(spell.end)}`;
      if (spell.end === end) return `${spell.phrase} after ${time(spell.start)}`;
      return `${spell.phrase} ${formatRange(spell.start, spell.end)}`;
    });
    if (!clauses.length) return "";
    return capitalize(clauses.length === 1 ? clauses[0] : `${clauses.slice(0, -1).join(", ")}, then ${clauses.at(-1)}`) + ".";
  }

  function narrative(period, now = Date.now()) {
    const official = period.detailedForecast?.trim() || "";
    const timing = forecastTiming(period, now);
    if (!timing) return official;
    // Keep the official temperatures, winds, amounts, and hazards. Replace only
    // straightforward wet timing and the separate day/night precipitation chance.
    const sentences = official.split(/(?<=[.!?])\s+(?=[A-Z])/);
    const details = sentences.flatMap(sentence => {
      if (/^Chance of precipitation is \d+%[.!]?$/i.test(sentence)) return [];
      if (!startsWithWet.test(sentence)) return [sentence];
      if (/\b(?:accumulation|amounts?|inches?|visibility|thunderstorms?|fog|wind|gusts?|high|low|temperature|ice|hazard)\b/i.test(sentence)) {
        const simpleTail = sentence.match(/,?\s+with\s+(a (?:high|low)\b[^.!?]*[.!?]?)$/i);
        if (!simpleTail || /\b(?:thunderstorms?|fog|wind|gusts?|ice|hazard)\b/i.test(sentence.slice(0, simpleTail.index))) return [sentence];
        return [capitalize(simpleTail[1])];
      }
      return [];
    });
    if (!details.some(sentence => /(?:^|[,;]\s+|\bwith\s+)(?:a\s+)?(?:high|low|temperature)\b/i.test(sentence)) && Number.isFinite(period.temperature)) {
      details.unshift(`${period.isDaytime ? "High" : "Low"} near ${period.temperature}°${period.temperatureUnit || "F"}.`);
    }
    return [timing, ...details].filter(Boolean).join(" ");
  }
  return {narrative};
})();
if (typeof module !== "undefined") module.exports = WeatherForecastProse;
