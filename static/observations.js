"use strict";
window.WeatherObservations=(()=>{
  const el=id=>document.getElementById(id);
  const endpoint="/api/observations",directions=["N","NE","E","SE","S","SW","W","NW"];
  const clock=new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric",timeZoneName:"short"});
  let data,active=false,busy=false;
  const degrees=value=>Number.isFinite(value)?`${value}°F`:"—";
  function windText(wind){
    if(!Number.isFinite(wind?.speedMph))return "—";
    if(wind.speedMph<=3)return "CALM";
    const direction=Number.isFinite(wind.direction)?directions[Math.round(wind.direction/45)%8]:wind.variable?"VRB":"";
    return [direction,wind.speedMph].filter(value=>value!=="").join(" ");
  }
  function timeText(hour){
    return clock.format(new Date(hour));
  }
  function render(){
    if(!active||!data)return;
    const latest=data.history[0];
    el("observations-temperature").textContent=degrees(latest?.tempF);
    el("observations-dewpoint").textContent=degrees(latest?.dewpointF);
    el("observations-wind").textContent=windText(latest?.wind);
    el("observations-time").textContent=latest?timeText(latest.hour):"Waiting for a complete hourly report.";
    const history=el("observations-history");
    history.replaceChildren();
    for(const hour of data.history){
      const row=document.createElement("tr");
      for(const text of [timeText(hour.hour),degrees(hour.tempF),degrees(hour.dewpointF),windText(hour.wind)]){
        const cell=document.createElement("td");
        cell.textContent=text;
        row.append(cell);
      }
      history.append(row);
    }
  }
  function adopt(next){
    if(!Array.isArray(next.history)||next.history.length>12)throw Error("Hourly reports are unavailable.");
    if(data===next||data&&next.checkedAt<data.checkedAt)return;
    data=next;
    render();
  }
  async function load(force=false){
    if(busy)return;
    busy=true;
    const button=el("refresh-observations");
    button.disabled=true;
    try{adopt(await window.WeatherPrepared.read(endpoint,{force}));}
    catch(error){if(!data)el("observations-time").textContent=error.message;}
    finally{busy=false;button.disabled=false;}
  }
  el("refresh-observations").addEventListener("click",()=>load(true));
  window.WeatherPrepared.subscribe(endpoint,adopt);
  setInterval(()=>{if(active&&!document.hidden)load(true);},30000);
  return {select(id){active=id==="observations";if(active){render();load();}},refresh(){if(active)load(true);}};
})();
