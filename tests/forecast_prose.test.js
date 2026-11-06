"use strict";
const assert = require("node:assert/strict");
const { narrative } = require("../static/forecast-prose.js");

const at = h => Date.parse(`2026-11-06T${String(h).padStart(2,"0")}:00:00-06:00`);
const window = (start, end, condition, maxChancePct, weather=[]) =>
  ({ startTime:new Date(at(start)).toISOString(), endTime:new Date(at(end)).toISOString(),
     condition, maxChancePct, weather });
const period = {
  startTime:new Date(at(6)).toISOString(), endTime:new Date(at(18)).toISOString(),
  temperature:51, temperatureUnit:"F", isDaytime:true,
  detailedForecast:"A 20 percent chance of rain before 8am, then rain likely. High near 51. Southeast wind 5 to 10 mph. Chance of precipitation is 70%. New precipitation amounts around 0.4 inches possible.",
  hourlyWindows:[window(6,8,"Slight Chance Rain",20),window(8,13,"Rain Showers Likely",70),window(13,18,"Rain Likely",70)]
};
assert.equal(narrative(period, at(5)), "A slight chance of rain before 8 AM, rain showers likely from 8 AM to 1 PM, then rain likely after 1 PM. High near 51. Southeast wind 5 to 10 mph. New precipitation amounts around 0.4 inches possible.");
assert.match(narrative(period, at(8)), /^Rain showers likely before 1 PM, then rain likely after 1 PM\./);
assert.equal(narrative({...period, hourlyWindows:period.hourlyWindows.slice(0,2)},at(5)), period.detailedForecast, "Incomplete hourly data keeps the full official forecast");
const dry = {...period, detailedForecast:"Mostly sunny, with a high near 51. West wind around 5 mph.", hourlyWindows:[window(6,18,"Mostly Sunny",0)]};
assert.equal(narrative(dry, at(5)), dry.detailedForecast);
const wet = {...period, detailedForecast:"Showers, with a high near 51. Gusts as high as 20 mph.", hourlyWindows:[window(6,18,"Showers",40,["Scattered rain showers (light)"])]};
assert.equal(narrative(wet, at(5)), "Scattered light rain showers. A high near 51. Gusts as high as 20 mph.");
const mixed = {...period, hourlyWindows:[window(6,18,"Rain And Snow",70)]};
assert.equal(narrative(mixed, at(5)), mixed.detailedForecast);
console.log("Forecast prose checks passed.");
