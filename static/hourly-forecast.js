"use strict";
window.WeatherHourlyForecast=(()=>{
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric"});
  const day=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric"});
  const node=(tag,cls,text)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(text!=null)el.textContent=text;return el;};
  const degrees=v=>Number.isFinite(v)?`${Math.round(v)}°F`:"—";
  const percent=v=>Number.isFinite(v)?`${Math.round(v)}%`:"—";
  function icon(condition,daytime){
    const wet=/rain|shower|drizzle|storm/i.test(condition),snow=/snow|sleet|ice/i.test(condition),fog=/fog|haze|smoke/i.test(condition);
    const cloudy=wet||snow||fog||/cloud|overcast/i.test(condition),partly=/partly|mostly clear|mostly sunny/i.test(condition);
    const sun='<circle cx="15" cy="14" r="6" fill="#f6c84b"/><path d="M15 3v3m0 16v3M4 14h3m16 0h3M7 6l2 2m12 12 2 2M7 22l2-2M21 8l2-2" stroke="#d7a52a" stroke-width="1.5"/>';
    const moon='<path d="M20 4a10 10 0 1 0 7 17A11 11 0 0 1 20 4Z" fill="#8ca5ce"/>';
    const cloud='<path d="M10 28a7 7 0 0 1-1-14 10 10 0 0 1 19-1 7.5 7.5 0 1 1 1 15Z" fill="#a8b7bc" stroke="#7b9198" stroke-width="1.2"/>';
    return `<svg viewBox="0 0 40 40" aria-hidden="true">${!cloudy||partly?(daytime===false?moon:sun):""}${cloudy?cloud:""}${wet?'<path d="m13 32-2 4m11-4-2 4m11-4-2 4" stroke="#4583b9" stroke-width="2" stroke-linecap="round"/>':""}${snow?'<g fill="#6599ba"><circle cx="12" cy="34" r="1.6"/><circle cx="22" cy="34" r="1.6"/><circle cx="31" cy="34" r="1.6"/></g>':""}${fog?'<path d="M6 31h28M9 35h23" stroke="#91a2a8" stroke-width="2"/>':""}${/storm|thunder/i.test(condition)?'<path d="m22 24-6 9h5l-2 7 10-12h-6l3-4Z" fill="#e7af34"/>':""}</svg>`;
  }
  function chart(hours,start){
    const low=Math.min(...hours.map(h=>h.temperatureF)),high=Math.max(...hours.map(h=>h.temperatureF));
    const y=v=>64-(v-low)/Math.max(high-low,4)*44,x=t=>20+(Date.parse(t)-start)/3600000/23*660;
    let path="",prior;
    for(const h of hours){const contiguous=prior&&Date.parse(h.startTime)-Date.parse(prior.startTime)===3600000;path+=`${contiguous?"L":"M"}${x(h.startTime).toFixed(1)} ${y(h.temperatureF).toFixed(1)} `;prior=h;}
    const labels=[0,6,12,23].map(i=>`<span>${clock.format(new Date(start+i*3600000))}</span>`).join("");
    return `<svg class="hourly-chart" viewBox="0 0 700 80" preserveAspectRatio="none" role="img" aria-label="24-hour temperature trend, ${Math.round(low)} to ${Math.round(high)} degrees Fahrenheit"><path d="M20 72H680" stroke="#e2e9e6"/><path d="${path}" fill="none" stroke="#25834e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg><div class="hourly-chart-labels">${labels}</div>`;
  }
  function render(data,now=Date.now()){
    const root=document.getElementById("forecast-hourly");
    const opened=new Set(Array.from(root.querySelectorAll?.("details[open]")||[]).map(el=>el.dataset.hour));
    root.replaceChildren();
    const start=Math.floor(now/3600000)*3600000,limit=start+24*3600000;
    const hours=(data.hourly||[]).filter(h=>Date.parse(h.startTime)>=start&&Date.parse(h.startTime)<limit&&Date.parse(h.endTime)>now&&Number.isFinite(h.temperatureF)).sort((a,b)=>Date.parse(a.startTime)-Date.parse(b.startTime));
    const heading=node("div","hourly-heading"),title=node("div");title.append(node("h2",null,"Next 24 hours"),node("p","hourly-source","Hopkins · NWS · Experimental"));heading.append(title);
    if(!hours.length){root.append(heading,node("p","hourly-empty","Hourly forecast is not ready. The text forecast is still available."));return;}
    heading.append(node("strong","hourly-range",`${Math.round(Math.min(...hours.map(h=>h.temperatureF)))}°–${Math.round(Math.max(...hours.map(h=>h.temperatureF)))}°F`));
    const overview=node("div","hourly-overview");overview.append(heading);const graph=node("div");graph.innerHTML=chart(hours,start);overview.append(graph);root.append(overview);
    const columns=node("div","hourly-columns");for(const label of ["Hour","","Temp","Conditions","Precip.",""])columns.append(node("span",null,label));root.append(columns);
    for(const hour of hours){
      const row=node("details","hourly-row");row.dataset.hour=hour.startTime;row.open=opened.has(hour.startTime);
      const summary=node("summary"),date=new Date(hour.startTime),when=node("span","hourly-when");when.append(node("strong",null,clock.format(date)),node("small",null,day.format(date)===day.format(new Date(now))?"Today":day.format(date)));
      const symbol=node("span","hourly-icon");symbol.innerHTML=icon(hour.condition||hour.nwsCondition||"",hour.isDaytime);
      const chance=node("span","hourly-chance",percent(hour.precipChancePct));chance.title="Chance of precipitation";
      summary.append(when,symbol,node("strong","hourly-temp",`${Math.round(hour.temperatureF)}°`),node("span","hourly-condition",hour.condition||"—"),chance,node("span","hourly-chevron","⌄"));
      const details=node("div","hourly-details");
      for(const [label,value] of [["Feels like",degrees(hour.feelsLikeF)],["Dewpoint",degrees(hour.dewpointF)],["Wind",[hour.windDirection,hour.windSpeed].filter(Boolean).join(" ")||"—"],["Cloud cover",percent(hour.cloudCoverPct)]]){
        const item=node("div");item.append(node("span",null,label),node("strong",null,value));details.append(item);
      }
      if(hour.weather?.length)details.append(node("p","hourly-weather",hour.weather.join(" · ")));
      row.append(summary,details);root.append(row);
    }
  }
  return {render};
})();
